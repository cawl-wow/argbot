import os
import logging
import models
import constants
import traceback

from lib.helpers import *
from models import UserPointBucket, Team

import csv

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('argbot.import')

if __name__ == "__main__":
    logger.setLevel(10)  # https://docs.python.org/2/library/logging.html#levels
    db_session = models.Session()

    for team in db_session.query(Team).all():
        for tiername in 'mc', 'bwl':
            filename = 'epgp_' + team.name.lower() + '_' + tiername + '.csv'
            with open('data/' + filename, mode='rt', buffering=1) as file:
                reader = csv.DictReader(file, delimiter=',')
                for row in reader:
                    try:
                        if tiername == 'mc':
                            tier = 1
                        elif tiername == 'bwl':
                            tier = 2

                        user = search_user(db_session, row['Name'])
                        if user is None:
                            logger.error("Couldn't find " + row['Name'] + "!")
                            continue
                        else:
                            logger.info("Loading EP and GP values")
                            ep_bucket = db_session.query(UserPointBucket) \
                                .filter(UserPointBucket.user == user,
                                        UserPointBucket.raid_tier == tier,
                                        UserPointBucket.team == team,
                                        UserPointBucket.point_type == PointTypes.EP) \
                                .one()
                            gp_bucket = db_session.query(UserPointBucket) \
                                .filter(UserPointBucket.user == user,
                                        UserPointBucket.raid_tier == tier,
                                        UserPointBucket.team == team,
                                        UserPointBucket.point_type == PointTypes.GP) \
                                .one()
                            ep_bucket.load_points(db_session, round(float(row['EP'])))
                            gp_bucket.load_points(db_session, round(float(row['GP'])))
                            logger.info("Finished with row " + str(row))
                    except Exception as e:
                        logger.error("Unable to load row because " + str(e))
                        logger.error(traceback.format_exc())
                        logger.debug("Row: " + str(row))
                        raise
    db_session.commit()
    db_session.close()
