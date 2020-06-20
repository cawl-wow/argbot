import os
import logging
import traceback
import csv
from requests_oauthlib import OAuth2Session
from oauthlib.oauth2 import BackendApplicationClient
from ratelimit import limits, sleep_and_retry

import models
import constants
from models import Item, ItemClasses, ItemSubClass





FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('argbot.setup')


def load_subclasses_from_blizzard(db_session, oa_session):
    for item_class in ItemClasses:
        logger.info("Loading subclasses for " + str(item_class.name))
        response = blizzard_lookup(oa_session,
                                   ("https://us.api.blizzard.com/data/wow/item-class/" + str(item_class.value)
                                    + "?namespace=static-classic-us&locale=en_US"))
        if response.status_code == 200:
            for subclass in response.json()['item_subclasses']:
                new_subclass = ItemSubClass(item_class=item_class, name=subclass['name'], subclass_id=subclass['id'])
                db_session.add(new_subclass)
        elif response.status_code == 404:
            logger.warning("Blizzard API couldn't find item class with id " + str(item_class.value))
    db_session.commit()


def load_items_from_blizzard():
    db_session = models.Session()
    BLIZZARD_API_CLIENT_ID = os.environ.get('BLIZZARD_API_CLIENT_ID')
    BLIZZARD_API_CLIENT_SECRET = os.environ.get('BLIZZARD_API_CLIENT_SECRET')

    blizzard_api_client = BackendApplicationClient(client_id=os.environ.get('BLIZZARD_API_CLIENT_ID'))
    oa_session = OAuth2Session(client=blizzard_api_client)
    token = oa_session.fetch_token(token_url='https://us.battle.net/oauth/token', client_id=BLIZZARD_API_CLIENT_ID,
                      client_secret=BLIZZARD_API_CLIENT_SECRET)
    load_subclasses_from_blizzard(db_session, oa_session)

    try:
        with open('data/dedupe_items.csv', mode='rt', buffering=1) as listfile:
            reader = csv.DictReader(listfile, delimiter=',')
            for row in reader:
                logger.debug("Processing row of :" + str(row))
                response = lookup_item(oa_session, row['entry'])
                if response.status_code == 200:
                    try:
                        data = response.json()
                        logger.info('Got an item')
                        #pprint.pprint(data)
                        if data['item_class']['name'] in set(itemclass.name for itemclass in ItemClasses):
                            media_url = get_item_media_url(oa_session, data['media']['key']['href'])
                            itemsubclass = db_session.query(ItemSubClass)\
                                .filter(ItemSubClass.item_class == ItemClasses[data['item_class']['name']])\
                                .filter(ItemSubClass.subclass_id == data['item_subclass']['id'])\
                                .one()
                            if data['inventory_type'].get('name'):
                                _inventory_type_name = data['inventory_type']['name']
                            else:
                                _inventory_type_name = None
                            new_item = Item(
                                id=data['id'],
                                name=data['name'],
                                item_level=data['level'],
                                required_level=data['required_level'],
                                icon_url=media_url,
                                item_class=ItemClasses[data['item_class']['name']],
                                item_subclass=itemsubclass,
                                quality=data['quality']['name'],
                                inventory_type=data['inventory_type']['type'],
                                inventory_type_name=_inventory_type_name,
                                max_count=data['max_count'])
                            db_session.add(new_item)
                        else:
                            logger.warning("Skipping item " + str(data['id']) + " because of unknown class name " + data['item_class']['name'])
                    except Exception as e:
                        logger.error("Failed to process item " + str(row['entry']))
                        logger.error(traceback.format_exc())
                        logger.debug("Item contents (if we got a response): " + str(data))
                        raise

                elif response.status_code == 404:
                    logger.warning("Got a 404 for item_list entry " + str(row))
                else:
                    logger.error("Blizzard didn't like something about our request for " + str(row))
                    logger.debug("Response data: " + str(data))
                if reader.line_num % constants.ITEM_LOAD_BATCH_SIZE == 0:
                    logger.info("Committing batch at " + str(reader.line_num))
                    db_session.commit()

            db_session.commit()
    except Exception as e:
        logger.error("Failed to load items because" + str(e))
        logger.error(traceback.format_exc())
        db_session.rollback()
    finally:
        db_session.close()



@sleep_and_retry
@limits(calls=95, period=1)
def blizzard_lookup(oa_session, url):
    return oa_session.get(url)

def lookup_item(oa_session, item_id):
    response = blizzard_lookup(oa_session=oa_session,
                               url=("https://us.api.blizzard.com/data/wow/item/" + str(item_id)
                                    + "?namespace=static-classic-us&locale=en_US")
                               )
    return response

def get_item_media_url(oa_session, href):
    response = blizzard_lookup(oa_session=oa_session,
                               url=href)
    if response.status_code == 200:
        if response.json().get('assets'):
            asset = response.json()['assets'][0]
            url = asset['value']
        else:
            logger.warning("No media returned.")
            url = None
    elif response.status_code == 404:
        logger.warning("Got 404 on item media for: " + str(href))
        url = None
    else:
        logger.error("Failed to retrieve media url for " + str(href))
        logger.debug("Response data: " + str(response))
        raise ValueError
    return url


if __name__ == "__main__":
    logger.setLevel(10)  # https://docs.python.org/2/library/logging.html#levels
    if os.environ.get('INIT_ARG_DB') == "TRUE":
        logger.warning("INIT_ARG_DB detected: Initializing database")
        if os.environ.get('ENVIRONMENT') != 'production':
            logger.warning("Environment isn't production, dropping db to recreate from scratch.")
            try:
                models.Base.metadata.drop_all(models.engine)
            except:
                pass

        models.Base.metadata.create_all(models.engine)
        models.seedSpecs()
        models.seedTeams()
        models.seedRewardSchedules()
        #models.seedSubclasses()

        # TODO if someFlagForAutomatedTesting
        #    models.seedUsers()
        #    models.seedChars()
        #    models.seedRaids()

    if os.environ.get('FULL_ITEM_LOAD') == "TRUE":
        load_items_from_blizzard()
    #else:
        #models.seedItems()

