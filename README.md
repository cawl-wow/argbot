# argbot
EP/GP Discord Bot for ASGARD coalition

Pre-Requisities for Development
* Blizzard API Key (https://develop.battle.net/)
* Discord bot token (https://www.writebots.com/discord-bot-token/) *TODO:  Add details for oAuth scope/permissions*
* Discord server with no other instances of Argbot connected

## Setup
1. Configure your local environment by creating a docker.env file with the following contents:
```
BLIZZARD_API_CLIENT_ID= 
BLIZZARD_API_CLIENT_SECRET= 
DISCORD_BOT_TOKEN=
POSTGRES_PASSWORD=
POSTGRES_USER=argbot
ENVIRONMENT=development
INIT_ARG_DB=TRUE
FULL_ITEM_LOAD=TRUE
PYTHONPATH=/argbot
```
*postgres_user and postgres_password can be any value, as the credentials will be both created and consumed simultaneously*

2. Build the docker containers
>docker-compose build

3. Start the database
>docker-compose up -d db

4. Seed the database with team and item information
>docker-compose run bot bash -c "python setup.py"

5. Run the bot
>docker-compose up 

6. Stop the bot
>docker-compose stop bot
