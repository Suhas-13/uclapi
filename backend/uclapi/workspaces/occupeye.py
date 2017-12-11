import json
import os
from base64 import b64encode
from collections import OrderedDict
from time import time as time_now
import redis
import requests

from django.conf import settings


class BadOccupEyeRequest(Exception):
    """
    Custom exception for when any CadCap API request fails.
    This should only be raised by endpoints that could contain
    user-entered data, so that we can give them an error telling
    them that the data they gave us is bad.
    """
    pass


class OccupEyeApi():
    """
    Python API for the Cad-Capture OccupEye backend.
    Data is cached as much as possible in Redis for performance.
    """
    # Keep general survey data around in the cache for a day
    SURVEY_TTL = 86400

    # Keep image data in the cache for two days
    IMAGE_TTL = 172800

    # Keep sensor data in the cache for a minute
    SENSOR_STATUS_TTL = 60

    def __init__(self, test_mode=False):
        self.r = redis.StrictRedis(
            host=settings.REDIS_UCLAPI_HOST,
            charset="utf-8",
            decode_responses=True
        )
        self.deployment_id = os.environ["OCCUPEYE_DEPLOYMENT_ID"]
        self.deployment_name = os.environ["OCCUPEYE_DEPLOYMENT_NAME"]
        self.base_url = os.environ["OCCUPEYE_BASE_URL"]

        # If either of those variables come up false, make sure
        # we have an access token before we continue.
        # We don't want to do anything manually in test mode to avoid
        # hitting environment variables we may not have yet.
        if test_mode:
            self.access_token = None
            self.access_token_expiry = None
        else:
            self.access_token = self.r.get("occupeye:access_token")

            access_token_expiry = self.r.get("occupeye:access_token_expiry")
            # We can only cast this value to an int if we know it's not None
            if access_token_expiry:
                self.access_token_expiry = int(access_token_expiry)
            else:
                self.access_token_expiry = None
            if not self.access_token or not self.access_token_expiry:
                self.get_token()

    def _str2bool(self, v):
        """
        Converts a string representation of a boolean
        into an actual boolean object. This is used
        to convert the boolean strings from Redis into
        actual bool objects.
        """
        return v.lower() in ("yes", "true", "t", "1")

    def get_token(self):
        """
        Gets a fresh OAuth 2.0 Bearer token based on the
        username and password stored in the environment.
        """
        url = self.base_url + "/token"
        body = {
            "Grant_type": "password",
            "Username": os.environ["OCCUPEYE_USERNAME"],
            "Password": os.environ["OCCUPEYE_PASSWORD"]
        }

        request = requests.post(
            url=url,
            data=body
        )

        response = json.loads(request.text)

        self.access_token = response["access_token"]
        self.access_token_expiry = int(time_now()) + int(
            response["expires_in"]
        )
        self.r.set("occupeye:access_token", self.access_token)
        self.r.set("occupeye:access_token_expiry", self.access_token_expiry)

    def token_valid(self):
        """
        Checks if the token exists and has not expired.
        """
        if not self.access_token:
            return False

        # Ensure the access token has not expired since we last checked
        if time_now() > self.access_token_expiry:
            return False

        return True

    def get_bearer_token(self):
        """
        If a token is valid, it returns the Bearer string
        used in the Authorization header.
        """
        if not self.token_valid():
            self.get_token()

        return "Bearer " + self.access_token

    def _cache_maps_for_survey(self, survey_id):
        """
        Every Survey (e.g. building) at UCL is comprised of many
        maps. A map may be a floor or wing. This function
        will cache data about those maps in Redis so that it
        can be quickly retrieved later.
        """
        survey_maps_key = "occupeye:surveys:{}:maps".format(
            survey_id
        )
        pipeline = self.r.pipeline()
        headers = {
            "Authorization": self.get_bearer_token()
        }
        url = "{}/api/Maps/?deployment={}&surveyid={}".format(
            self.base_url,
            self.deployment_name,
            survey_id
        )
        request = requests.get(
            url=url,
            headers=headers
        )
        survey_maps_data = request.json()

        pipeline.delete(survey_maps_key)
        for survey_map in survey_maps_data:
            survey_map_id = "occupeye:surveys:{}:maps:{}".format(
                survey_id,
                str(survey_map["MapID"])
            )
            pipeline.hmset(
                survey_map_id,
                {
                    "id": survey_map["MapID"],
                    "name": survey_map["MapName"],
                    "image_id": survey_map["ImageID"]
                }
            )
            pipeline.rpush(
                survey_maps_key,
                survey_map["MapID"]
            )
            pipeline.expire(
                survey_map_id,
                self.SURVEY_TTL
            )
        pipeline.expire(
            survey_maps_key,
            self.SURVEY_TTL
        )
        pipeline.execute()

    def _cache_survey_data(self):
        """
        This function will cache all surveys (e.g. buildings) in
        the OccupEye system. It makes use of the _cache_maps_for_survey
        helper function above to tie all maps to surveys.
        """
        # Use a Redis Pipeline to ensure that all the data is inserted together
        # and atomically
        pipeline = self.r.pipeline()
        # Ensure that the list of occupeye surveys has actually been cleared
        pipeline.delete("occupeye:surveys")

        headers = {
            "Authorization": self.get_bearer_token()
        }
        url = "{}/api/Surveys/?deployment={}".format(
            self.base_url,
            self.deployment_name
        )
        request = requests.get(
            url=url,
            headers=headers
        )
        surveys_data = request.json()

        for survey in surveys_data:
            survey_key = "occupeye:surveys:" + str(survey["SurveyID"])
            pipeline.hmset(
                survey_key,
                {
                    "id": survey["SurveyID"],
                    "active": survey["Active"],
                    "name": survey["Name"],
                    "start_time": survey["StartTime"],
                    "end_time": survey["EndTime"]
                }
            )
            pipeline.expire(survey_key, self.SURVEY_TTL)
            # We prepend to the list of Surveys because the API returns
            # a list of surveys where the ID decrements
            pipeline.lpush("occupeye:surveys", str(survey["SurveyID"]))
            # Cache all maps for this survey for later use
            self._cache_maps_for_survey(survey["SurveyID"])

        pipeline.expire("occupeye:surveys", self.SURVEY_TTL)
        pipeline.execute()

    def get_surveys(self):
        """
        Serialises all surveys and maps to a dictionary
        object that can be returned to the user. If the
        requisite data does not exist in Redis, it is cached using
        the helper functions above, then returned from the cache.
        """
        if self.r.llen("occupeye:surveys") == 0:
            # The data is not in the cache, so cache it.
            self._cache_survey_data()

        # Now we know we have the data cached, we can serve it
        survey_ids = self.r.lrange(
            "occupeye:surveys",
            0,
            self.r.llen("occupeye:surveys") - 1
        )

        surveys = []

        for survey_id in survey_ids:
            survey_data = self.r.hgetall("occupeye:surveys:" + survey_id)
            survey = {
                "id": int(survey_data["id"]),
                "name": survey_data["name"],
                "active": self._str2bool(survey_data["active"]),
                "start_time": survey_data["start_time"],
                "end_time": survey_data["end_time"]
            }
            survey_map_ids_list = "occupeye:surveys:{}:maps".format(
                survey_id
            )
            survey_map_ids = self.r.lrange(
                survey_map_ids_list,
                0,
                self.r.llen(survey_map_ids_list)
            )
            survey_maps = []
            for survey_map_id in survey_map_ids:
                survey_map = self.r.hgetall(
                    "occupeye:surveys:{}:maps:{}".format(
                        survey_id,
                        survey_map_id
                    )
                )
                survey_maps.append(
                    {
                       "id": int(survey_map["id"]),
                       "name": survey_map["name"],
                       "image_id": int(survey_map["image_id"])
                    }
                )
            survey["maps"] = survey_maps
            surveys.append(survey)
        return surveys

    def _cache_image(self, image_id):
        """
        Downloads map images from the API and stores their
        base64 representation and associated data type in Redis.
        """
        headers = {
            "Authorization": self.get_bearer_token()
        }
        url = "{}/api/images/{}?deployment={}".format(
            self.base_url,
            image_id,
            self.deployment_name
        )
        try:
            request = requests.get(
                url=url,
                headers=headers,
                stream=True
            )
            content_type = request.headers['Content-Type']
        except:
            raise BadOccupEyeRequest

        raw_image = request.content
        image_b64 = b64encode(raw_image)

        pipeline = self.r.pipeline()
        pipeline.set(
            "occupeye:image:{}:base64".format(image_id),
            image_b64
        )
        pipeline.expire(
            "occupeye:image:{}:base64".format(image_id),
            self.IMAGE_TTL
        )
        pipeline.set(
            "occupeye:image:{}:content_type".format(image_id),
            content_type
        )
        pipeline.expire(
            "occupeye:image:{}:content_type".format(image_id),
            self.IMAGE_TTL
        )
        pipeline.execute()

    def get_image(self, image_id):
        """
        Pulls an Image ID requested by the user from Redis.
        """
        # We must ensure that only digits are passed into the code
        # to prevent Redis injection attacks.
        if not image_id.isdigit():
            raise BadOccupEyeRequest

        if not self.r.exists("occupeye:image:{}:base64".format(image_id)):
            self._cache_image(image_id)

        image_b64 = self.r.get("occupeye:image:{}:base64".format(image_id))
        content_type = self.r.get(
            "occupeye:image:{}:content_type".format(image_id)
        )

        return (image_b64, content_type)

    def _cache_all_survey_sensor_states(self, survey_id):
        """
        Caches all sensors in a survey, including their latest states
        """
        headers = {
            "Authorization": self.get_bearer_token()
        }
        url = "{}/api/SurveySensorsLatest/{}?deployment={}".format(
            self.base_url,
            survey_id,
            self.deployment_name
        )
        request = requests.get(
            url=url,
            headers=headers
        )
        all_sensors_data = request.json()
        pipeline = self.r.pipeline()
        pipeline.delete(
            "occupeye:surveys:{}:sensors".format(survey_id)
        )
        for sensor_data in all_sensors_data:
            sensor_data_key = "occupeye:surveys:{}:sensors:{}:data".format(
                survey_id,
                sensor_data["HardwareID"]
            )
            pipeline.hmset(
                sensor_data_key,
                {
                    "hardware_id": sensor_data["HardwareID"],
                    "sensor_id": sensor_data["SensorID"],
                }
            )

            sensor_status_key = "occupeye:surveys:{}:sensors:{}:status".format(
                survey_id,
                sensor_data["HardwareID"]
            )
            pipeline.hmset(
                sensor_status_key,
                {
                    "id": sensor_data["HardwareID"],
                    "last_trigger_type": sensor_data["LastTriggerType"],
                    "last_trigger_timestamp": sensor_data["LastTriggerTime"]
                }
            )
            pipeline.rpush(
                "occupeye:surveys:{}:sensors".format(survey_id),
                sensor_data["HardwareID"]
            )
            pipeline.expire(sensor_data_key, self.SURVEY_TTL)
            pipeline.expire(sensor_status_key, self.SENSOR_STATUS_TTL)

        pipeline.expire(
            "occupeye:surveys:{}:sensors".format(survey_id),
            self.SURVEY_TTL
        )

        pipeline.execute()

    def _cache_sensors_for_map(self, survey_id, map_id):
        """
        Caches a list of every sensor associated with the
        Map ID requested.
        """
        headers = {
            "Authorization": self.get_bearer_token()
        }
        url = "{}/api/Maps/{}?deployment={}&origin=tl".format(
            self.base_url,
            map_id,
            self.deployment_name
        )
        request = requests.get(
            url=url,
            headers=headers
        )
        all_map_sensors_data = request.json()

        pipeline = self.r.pipeline()
        map_sensors_list_key = "occupeye:surveys:{}:maps:{}:sensors".format(
            survey_id,
            map_id
        )
        pipeline.delete(map_sensors_list_key)

        # Cache a list of every HardwareID associated with the survey map
        # and also sore the co-ordinates of each sensor for when we
        # implement mapping functionality
        for map_sensor_data in all_map_sensors_data["MapItemViewModels"]:
            pipeline.rpush(
                map_sensors_list_key,
                map_sensor_data["HardwareID"]
            )
            properties_key = "{}:{}:properties".format(
                map_sensors_list_key,
                map_sensor_data["HardwareID"]
            )
            pipeline.hmset(
                properties_key,
                {
                    "id": map_sensor_data["HardwareID"],
                    "x_pos": map_sensor_data["X"],
                    "y_pos": map_sensor_data["Y"]
                }
            )
            pipeline.expire(
                properties_key,
                self.SURVEY_TTL
            )

        pipeline.expire(
            map_sensors_list_key,
            self.SENSOR_STATUS_TTL
        )
        pipeline.execute()

    def get_survey_sensors(self, survey_id, return_states=True):
        """
        Gets all sensors in a survey and optionally returns
        their statuses.
        """
        # Check whether the Survey ID requested is actually
        # an integer.
        if not survey_id.isdigit():
            raise BadOccupEyeRequest

        maps_key = "occupeye:surveys:{}:maps".format(survey_id)
        # Check if we have a list of maps for this survey
        if not self.r.llen(maps_key):
            self._cache_survey_data()

        # If the data still doesn't exist, the map probably doesn't
        # exist, so raise an error.
        if not self.r.llen(maps_key):
            raise BadOccupEyeRequest

        maps = self.r.lrange(
            maps_key,
            0,
            self.r.llen(maps_key)
        )

        data = {"maps": []}

        for map_id in maps:
            map_sensors_key = "occupeye:surveys:{}:maps:{}:sensors".format(
                survey_id,
                map_id
            )
            if not self.r.llen(map_sensors_key):
                self._cache_sensors_for_map(survey_id, map_id)

            sensor_hw_ids = self.r.lrange(
                map_sensors_key,
                0,
                self.r.llen(map_sensors_key)
            )

            sensors = OrderedDict()

            pipeline = self.r.pipeline()

            # Get sensor properties requests into a pipeline
            for sensor_id in sensor_hw_ids:
                sensor_properties_key = (
                    "occupeye:surveys:{}:maps:{}:sensors:{}:properties"
                ).format(survey_id, map_id, sensor_id)
                pipeline.hgetall(sensor_properties_key)

            # Now execute that pipeline
            for result in pipeline.execute():
                sensors[result['id']] = result

            # Now do the same thing again if states were requested
            if return_states:
                # All HW sensor state values have the same TTL and are added
                # using a transaction, so we can check just the first sensor
                # HW ID. If we have data on it, we assume we can use the cache.
                # If not, we retrieve all the latest data.
                first_sensor_status_key = (
                    "occupeye:surveys:{}:maps:{}:sensors:{}:status"
                ).format(survey_id, map_id, sensor_hw_ids[0])
                if not self.r.get(first_sensor_status_key):
                    self._cache_all_survey_sensor_states(survey_id)

                for sensor_id in sensor_hw_ids:
                    sensor_status_key = (
                         "occupeye:surveys:{}:sensors:{}:status"
                    ).format(survey_id, sensor_id)
                    pipeline.hgetall(sensor_status_key)

                for result in pipeline.execute():
                    if result:
                        sensors[result['id']][
                            "last_trigger_timestamp"
                        ] = result["last_trigger_timestamp"]
                        sensors[result['id']][
                            "last_trigger_type"
                        ] = result["last_trigger_type"]

            map_data = self.r.hgetall(
                "occupeye:surveys:{}:maps:{}".format(survey_id, map_id)
            )
            pipeline.execute()
            map_data["sensors"] = sensors

            data["maps"].append(map_data)

        return data
