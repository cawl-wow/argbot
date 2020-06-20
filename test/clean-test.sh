#!/bin/bash
docker container prune 
docker volume prune 
docker-compose build
docker-compose up
