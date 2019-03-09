# -*- coding: utf-8 -*-
# Generated by Django 1.11.18 on 2019-02-06 01:55
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timetable',
         '0014_auto_20190302_0232_squashed_0019_auto_20190305_1729'),
    ]

    operations = [
        migrations.CreateModel(
            name='CrsavailmodulesA',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('setid', models.TextField(max_length=10)),
                ('courseid', models.TextField(max_length=12)),
                ('crsyear', models.BigIntegerField(blank=True, null=True)),
                ('groupnum', models.BigIntegerField(blank=True, null=True)),
                ('deptid', models.TextField(max_length=10)),
                ('moduleid', models.TextField(max_length=12)),
                ('instid', models.BigIntegerField(blank=True, null=True)),
                ('semid', models.BigIntegerField(blank=True, null=True)),
                ('unitvalue', models.TextField(max_length=19)),
                ('crsver', models.BigIntegerField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='CrsavailmodulesB',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('setid', models.TextField(max_length=10)),
                ('courseid', models.TextField(max_length=12)),
                ('crsyear', models.BigIntegerField(blank=True, null=True)),
                ('groupnum', models.BigIntegerField(blank=True, null=True)),
                ('deptid', models.TextField(max_length=10)),
                ('moduleid', models.TextField(max_length=12)),
                ('instid', models.BigIntegerField(blank=True, null=True)),
                ('semid', models.BigIntegerField(blank=True, null=True)),
                ('unitvalue', models.TextField(max_length=19)),
                ('crsver', models.BigIntegerField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='CrscompmodulesA',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('setid', models.TextField(max_length=10)),
                ('courseid', models.TextField(max_length=12)),
                ('crsyear', models.BigIntegerField(blank=True, null=True)),
                ('deptid', models.TextField(max_length=10)),
                ('moduleid', models.TextField(max_length=12)),
                ('instid', models.BigIntegerField(blank=True, null=True)),
                ('semid', models.BigIntegerField(blank=True, null=True)),
                ('unitvalue', models.TextField(max_length=19)),
                ('crsver', models.BigIntegerField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='CrscompmodulesB',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('setid', models.TextField(max_length=10)),
                ('courseid', models.TextField(max_length=12)),
                ('crsyear', models.BigIntegerField(blank=True, null=True)),
                ('deptid', models.TextField(max_length=10)),
                ('moduleid', models.TextField(max_length=12)),
                ('instid', models.BigIntegerField(blank=True, null=True)),
                ('semid', models.BigIntegerField(blank=True, null=True)),
                ('unitvalue', models.TextField(max_length=19)),
                ('crsver', models.BigIntegerField(blank=True, null=True)),
            ],
        ),
    ]
