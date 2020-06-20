import traceback
import logging
import models
import worker
import datetime
from models import ActiveRaidTiers, CharacterRoles, CharacterClass, Spec, Character, Team, Raid, Item, User, RaidZone, \
    Signup, PointTypes, UserPointBucket, ItemDrop, ItemDropBid, Bids

logger = logging.getLogger('argbot.helpers')


def parse_message_args(content):
    return content.replace('  ', ' ').split(' ')


def fieldvalue_from_characters(characters):
    _charlist = ""
    if not characters:
        logger.info("Charlist is false, returning null space")
        _charlist = "** ** ** **"  # Generate blank space in table on discord
    else:
        logger.info("Got a list for signups")
        _charlist = ("\r\n".join(characters))

    return _charlist


def stringify_bids(bid_pr_list):
    string = ""
    if bid_pr_list:
        for bidder in bid_pr_list:
            logger.debug("Bidder is " + str(bidder[0]))
            string += bidder[0].character.name + " (" + str(bidder[1]) + ")\r\n"
    else:
        string = "** **"  # Closest to &nbsp in Discord markup
    return string


def search_user(session, search_param):
    logger.info("Searching for tagged user from message contents")
    if search_param.startswith('<@!'):
        logger.debug("Search search_param looks like a mention, lets parse it")
        _search_param_id = search_param.split('!')[1].replace('>', '')
        logger.debug("Searching for user ID =" + str(int(_search_param_id)))
        _user = session.query(User).filter(User.id == int(_search_param_id)).one_or_none()
    else:
        logger.info("Didn't find tag format for @user, searching by raw name instead")
        if search_param.startswith('@'):
            logger.info("Looks like an attempted mention that didn't link, lets remove the @")
            search_param = search_param.replace('@', '')
        _user = session.query(User).filter(User.display_name.ilike(search_param + '%')).one_or_none()

    if _user is None:
        logger.info("Didn't find any users.  Searching for character name instead")
        _character = session.query(Character).filter(Character.name.ilike(search_param + '%')).one_or_none()
        if _character:
            _user = _character.user
        else:
            logger.error("Couldn't find user by tag, name, or character name.")

    return _user


def paint_time(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%B %d %Y %I:%M %p")
    else:
        raise TypeError
