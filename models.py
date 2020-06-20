import os
import enum
import logging
import random
from collections import namedtuple
from constants import *
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.sql import func
from sqlalchemy import Column, Boolean, BigInteger, Integer, Interval, String, Enum, DateTime, ForeignKey, Table, \
    Numeric, ForeignKeyConstraint
from sqlalchemy.orm import sessionmaker, relationship
from operator import itemgetter
from datetime import datetime, timedelta

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('argbot.models')
logger.setLevel(10)  # https://docs.python.org/2/library/logging.html#levels

Base = declarative_base()

ENVIRONMENT = os.environ['ENVIRONMENT']


def get_db_uri():
    if ENVIRONMENT == 'test':
        url = 'sqlite:///:memory:'
    else:
        if os.environ.get('DB_HOST') is not None:
            DB_HOST = os.environ.get('DB_HOST')
        else:
            DB_HOST = 'db'

        if os.environ.get('DB_USER') is not None:
            DB_USER = os.environ.get('DB_USER')
        elif os.environ.get('DB_USER') is None and os.environ.get('POSTGRES_USER') is not None:
            DB_USER = os.environ.get('POSTGRES_USER')
        else:
            DB_USER = 'postgres'

        if os.environ.get('DB_PASSWORD') is not None:
            DB_PASSWORD = os.environ.get('DB_PASSWORD')
        elif os.environ.get('POSTGRES_PASSWORD') is not None:
            DB_PASSWORD = os.environ.get('POSTGRES_PASSWORD')
        else:
            raise KeyError("Neither DB_PASSWORD nor POSTGRES_PASSWORD found in the environment.")

        if os.environ.get('DB_PORT') is not None:
            DB_PORT = os.environ.get('DB_PORT')
        else:
            DB_PORT = '5432'

        if os.environ.get('DB_NAME') is not None:
            DB_NAME = os.environ.get('DB_NAME')
        else:
            DB_NAME = DB_USER

        url = 'postgres://' + DB_USER + ':' + DB_PASSWORD + '@' + DB_HOST + ':' + DB_PORT + '/' + DB_NAME

    return url


engine = create_engine(get_db_uri())
# 'postgresql://' + DB_USER + ':' + DB_PASSWORD + '@' + DB_HOST + ':' + DB_PORT + '/' + DB_NAME)


Session = sessionmaker()
Session.configure(bind=engine)
# End DB Setup


""" Notes from discord

 person = a discord account
a person has many characters
a character is assigned to a team
a team has many raids
a raid has an instance and a schedule and a reward_schema
A user has an ep_bucket and a gp_bucket for each team's each raid tier


"""

RaidTier = namedtuple('RaidTier', 'name tier')


ActiveRaidTiers = [RaidTier('MC/ONY', 1), RaidTier('BWL', 2)]


class PointTypes(enum.Enum):
    EP = 1
    GP = 2


class CharacterRoles(enum.Enum):
    Tank = 1
    Healer = 2
    Melee = 3
    Ranged = 4
    Caster = 5


class CharacterClass(enum.Enum):
    # https://us.api.blizzard.com/data/wow/playable-class/?namespace=static-1.13.3_32760-classic-us"
    Warrior = 1
    Paladin = 2
    Hunter = 3
    Rogue = 4
    Priest = 5
    Shaman = 7
    Mage = 8
    Warlock = 9
    Druid = 11


class RaidZone(enum.Enum):
    WORLD = 0
    MC = 1
    ONY = 2
    BWL = 3
    ZG = 4
    AQ40 = 5
    AQ20 = 6
    NAXX = 7


class RaidTiers(enum.Enum):
    MC_ONY = 1
    BWL = 2
    AQ = 3
    NAXX = 4


class ItemClasses(enum.Enum):
    Consumable = 0
    Container = 1
    Weapon = 2
    Armor = 4
    Reagent = 5
    Projectile = 6
    TradeGoods = 7
    Recipe = 9
    Quiver = 11
    Quest = 12
    Key = 13
    Miscellaneous = 15


class WeaponSubclasses(enum.Enum):
    Axe = 0
    Axe2 = 1
    Bow = 2
    Gun = 3
    Mace = 4
    Mace2 = 5
    Polearm = 6
    Sword = 7
    Sword2 = 8
    Staff = 10
    Exotic = 11
    Exotic2 = 12
    Fist = 13
    Misc = 14
    Dagger = 15
    Thrown = 16
    Spear = 17
    Crossbow = 18
    Wand = 19
    Fishing = 20


class ArmorSubclasses(enum.Enum):
    Cloth = 1
    Leather = 2
    Mail = 3
    Plate = 4
    Shield = 6
    Libram = 7
    Idol = 8
    Totem = 9


class PointTransactionTypes(enum.Enum):
    INIT = 0
    GRANT = 1
    DECAY = 2
    EDIT = 3
    LOAD = 4
    PENALTY = 5
    TRUNCATE = 6
    REVERSE = 7


class Spec(Base):
    __tablename__ = 'specs'
    id = Column(Integer, primary_key=True)
    character_class = Column(Enum(CharacterClass))
    name = Column(String)
    role = Column(Enum(CharacterRoles))
    emoticon_name = Column(String)
    emoticon_id = Column(BigInteger)

    def __str__(self):
        return (self.name + ' ' + self.character_class.name)


class User(Base):
    # https://discordpy.readthedocs.io/en/latest/api.html#member
    __tablename__ = 'users'
    id = Column(BigInteger, primary_key=True)
    discord_guild_id = Column(BigInteger)
    name = Column(String)
    display_name = Column(String)

    def find_or_init_bucket(self, session, team, raid_tier, point_type):
        try:
            ##logger.info("Searching for existing bucket")
            bucket = session.query(UserPointBucket).filter(
                UserPointBucket.user == self,
                UserPointBucket.team == team,
                UserPointBucket.raid_tier == raid_tier,
                UserPointBucket.point_type == point_type).one_or_none()
            if bucket is None:
                logger.info("Bucket not found, creating anew and initializing")
                _new_bucket = UserPointBucket(user=self, team=team, raid_tier=raid_tier, point_type=point_type)
                session.add(_new_bucket)
                _new_bucket.init_points(session=session)
                session.commit()
                bucket = _new_bucket
            else:
                # logger.info("Found existing bucket, returning")
                pass
            return bucket
        except Exception as e:
            # logger.error("Unable to find or create bucket for user because " + str(e))
            session.rollback()
            raise e

    def find_characters(self, session, role=None, character_class=None):
        try:
            results = None
            query = session.query(Character).join(Character.spec).filter(Character.user == self)
            if role:
                query.filter(Spec.role == role)
            if character_class:
                query.filter(Spec.character_class == character_class)
            results = query.all()
        except Exception as e:
            logger.error("Unable to lookup user's characters because: " + str(e))
            session.rollback()
            raise
        return results


class RewardSchedule(Base):
    __tablename__ = 'reward_schedules'
    team_id = Column(Integer, ForeignKey('teams.id'), primary_key=True)
    zone = Column(Enum(RaidZone), primary_key=True)
    signin_interval = Column(Interval)
    start_bonus = Column(Integer)
    tick_bonus = Column(Integer)
    tick_interval = Column(Interval)
    duration = Column(Interval)
    end_bonus = Column(Integer)
    team = relationship('Team')


class Raid(Base):
    __tablename__ = 'raids'
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey('teams.id'))
    zone = Column(Enum(RaidZone))
    starts_at = Column(DateTime)
    ends_at = Column(DateTime)
    notes = Column(String)
    signup_message_channel_id = Column(BigInteger)
    signup_message_id = Column(BigInteger)
    created_by_id = Column(BigInteger, ForeignKey('users.id'))
    is_started = Column(Boolean, default=False)
    is_closed = Column(Boolean, default=False)
    reward_schedule = relationship('RewardSchedule', viewonly=True)
    team = relationship('Team')
    created_by = relationship('User')
    __table_args__ = (ForeignKeyConstraint([team_id, zone], [RewardSchedule.team_id, RewardSchedule.zone]), {})

    def __str__(self):
        return (self.team.name + " is going to " + self.zone.name + " at " + paint_time(self.starts_at))

    def get_tier(self):
        if (self.zone == RaidZone.WORLD or self.zone == RaidZone.ZG):
            return 0
        elif (self.zone == RaidZone.MC or self.zone == RaidZone.ONY):
            return 1
        elif (self.zone == RaidZone.BWL):
            return 2
        elif (self.zone == RaidZone.AQ40 or self.zone == RaidZone.AQ20):
            return 3
        elif (self.zone == RaidZone.NAXX):
            return 4
        else:
            return -1

    def reward(self, session):
        logger.info("Processing raid reward tick for raid " + str(self.id))
        try:
            if self.is_started == False:
                for signup in self.signups:
                    signup.give_effort(session, self.reward_schedule.start_bonus)
                self.is_started = True
            else:
                for signup in self.signups:
                    signup.give_effort(session, self.reward_schedule.tick_bonus)
                    if datetime.utcnow() > self.ends_at:
                        signup.give_effort(session, self.reward_schedule.end_bonus)
                if datetime.utcnow() > self.ends_at:
                    self.is_closed = True
            session.commit()
        except Exception as e:
            logger.error("Failed to process raid reward because " + str(e))
            session.rollback()
            raise e

    def extend(self, session, interval):
        logger.info("Extending raid ends_at")
        if self.is_closed == False:
            self.ends_at += interval
            session.commit()
        else:
            raise ValueError("Raid is already closed and cannot be extended.")
        return


roster_table = Table('rosters', Base.metadata,
                     Column('team_id', Integer, ForeignKey('teams.id'), primary_key=True),
                     Column('character_id', Integer, ForeignKey('characters.id'), primary_key=True)
                     )


class Character(Base):
    __tablename__ = 'characters'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'))
    name = Column(String)
    character_guild = Column(String)
    spec_id = Column(Integer, ForeignKey('specs.id'))
    user = relationship('User', backref='characters')
    rosters = relationship('Team', secondary=roster_table)
    spec = relationship('Spec', backref='characters')

    def __str__(self):
        string = (self.name + ' ' + str(self.spec))
        if self.character_guild is not None:
            string += (' of <' + str(self.character_guild) + '> ')
        return string


class Signup(Base):
    __tablename__ = 'signups'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'))
    character_id = Column(Integer, ForeignKey('characters.id'))
    raid_id = Column(Integer, ForeignKey('raids.id'))
    signup_at = Column(DateTime)
    is_confirmed = Column(Boolean, default=False)
    confirmed_at = Column(DateTime)
    is_ejected = Column(Boolean, default=False)
    ejected_at = Column(DateTime)
    is_rescinded = Column(Boolean, default=False)
    rescinded_at = Column(DateTime)
    user = relationship('User')
    character = relationship('Character')
    raid = relationship('Raid', backref='signups')

    def give_effort(self, session, effort_amount):
        logger.info("About to look for bucket to give_effort")
        _bucket = session.query(UserPointBucket).filter(UserPointBucket.user == self.user,
                                                        UserPointBucket.team == self.raid.team,
                                                        UserPointBucket.raid_tier == self.raid.get_tier(),
                                                        UserPointBucket.point_type == PointTypes.EP).one()

        if _bucket is None:
            raise ValueError("Can't grant effort to a null bucket")
        if self.is_confirmed == True and self.is_ejected == False:
            logger.info("Proceeding with grant")
            _bucket.grant_points(session=session, delta_points=effort_amount, raid=self.raid, character=self.character)
        else:
            logger.info("Ignoring effort from " + str(self.user_id) + " because " + str(self.is_confirmed) + " " + str(
                self.is_ejected))
            pass
        return

    def confirm(self):
        if not self.is_confirmed:
            self.is_confirmed = True
            self.confirmed_at = datetime.utcnow()


class Team(Base):
    __tablename__ = 'teams'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    description = Column(String)
    voice_channel_id = Column(BigInteger)
    raiders = relationship('Character', secondary=roster_table)

    def __str__(self):
        output = "Team " + self.name + " Overview \r\n"
        for member in self.raiders:
            output += " - " + str(member)
        return output

    def assign(self, session, character):
        if self not in character.rosters:
            character.rosters.append(self)
            user = character.user
            for _tier in range(5):  # 0 through 4 bad hardcode for set(raid_tiers.get_tier)
                for _point_type in PointTypes:
                    logger.debug(
                        "Find or creating " + user.display_name + '  ' + str(_point_type) + " bucket for tier " + str(
                            _tier) + " for team "
                        + self.name)
                    user.find_or_init_bucket(session=session, team=self, raid_tier=_tier, point_type=_point_type)
        else:
            logger.warning("Couldn't assign " + character.name + " to team " + self.name + ", they are already on it!")
        return


class ItemSubClass(Base):
    __tablename__ = 'item_subclasses'
    item_class = Column(Enum(ItemClasses), primary_key=True)
    subclass_id = Column(Integer, primary_key=True)
    name = Column(String)


class Item(Base):
    __tablename__ = 'items'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    item_level = Column(Integer)
    required_level = Column(Integer)
    icon_url = Column(String)
    item_class = Column(Enum(ItemClasses))
    item_subclass_id = Column(Integer)
    quality = Column(String)
    inventory_type = Column(String)
    inventory_type_name = Column(String)
    max_count = Column(Integer)
    __table_args__ = (
        ForeignKeyConstraint([item_class, item_subclass_id], [ItemSubClass.item_class, ItemSubClass.subclass_id]), {})
    item_subclass = relationship('ItemSubClass')

    def __str__(self):
        return (self.name + ", a " + self.item_subclass.name)

    def gp(self, role=None):
        slot_modifier = 0
        # Using slot modifier logic from here: http://www.epgpweb.com/help/gearpoints
        if self.item_class == ItemClasses.Weapon:
            logger.debug("I'm a weapon with subclass = " + str(self.item_subclass_id))
            if self.item_subclass_id in [WeaponSubclasses.Axe2.value, WeaponSubclasses.Mace2.value,
                                         WeaponSubclasses.Sword2.value, WeaponSubclasses.Staff.value,
                                         WeaponSubclasses.Exotic2.value, WeaponSubclasses.Spear.value]:
                if role == CharacterRoles.Ranged:
                    slot_modifier = 1
                else:
                    slot_modifier = 2
            elif self.item_subclass_id in [WeaponSubclasses.Axe.value, WeaponSubclasses.Mace.value,
                                           WeaponSubclasses.Sword.value, WeaponSubclasses.Exotic.value,
                                           WeaponSubclasses.Fist.value, WeaponSubclasses.Dagger.value]:
                if role == CharacterRoles.Tank:
                    slot_modifier = 0.5
                elif role == CharacterRoles.Ranged:
                    slot_modifier = 0.5
                else:
                    slot_modifier = 1
            elif self.item_subclass_id in [WeaponSubclasses.Bow.value, WeaponSubclasses.Gun.value,
                                           WeaponSubclasses.Thrown.value, WeaponSubclasses.Crossbow.value,
                                           WeaponSubclasses.Wand.value]:
                if role == CharacterRoles.Ranged:
                    slot_modifier = 1.5
                else:
                    slot_modifier = 0.5
        elif self.item_class == ItemClasses.Armor:
            logger.debug("I'm armor with subclass =" + str(self.item_subclass_id))
            if self.item_subclass_id == ArmorSubclasses.Shield.value and role == CharacterRoles.Tank:
                slot_modifier = 1.5
            elif self.item_subclass in [ArmorSubclasses.Libram.value, ArmorSubclasses.Idol.value,
                                        ArmorSubclasses.Totem.value]:
                slot_modifier = 0.5
            else:
                if self.inventory_type_name in ['Head', 'Chest', 'Legs']:
                    slot_modifier = 1
                elif self.inventory_type_name in ['Shoulder', 'Hands', 'Waist', 'Feet', 'Trinket']:
                    slot_modifier = 0.75
                elif self.inventory_type_name in ['Wrist', 'Neck', 'Back', 'Finger']:
                    slot_modifier = 0.5

        quality_value = 0
        if self.quality == 'Legendary':
            quality_value = 5
        elif self.quality == 'Epic':
            quality_value = 4
        elif self.quality == 'Rare':
            quality_value = 3
        elif self.quality == 'Uncommon':
            quality_value = 2

        logger.debug("Calculating GP with the following values.  ilvl=" + str(self.item_level) + ", slot_mod=" + str(
            slot_modifier) + ", qval=" + str(quality_value))
        gp_value = int(round((17.213 * 2 ** (self.item_level / 26 + (quality_value - 4)) * slot_modifier), 0))
        # To maintain consistency I'm using the formula from here: https://gitlab.com/Korkd/epgpbot/-/wikis/epgp
        return gp_value


class ItemDrop(Base):
    __tablename__ = 'item_drops'
    id = Column(BigInteger, primary_key=True)
    item_id = Column(Integer, ForeignKey('items.id'))
    raid_id = Column(Integer, ForeignKey('raids.id'))
    created_by_id = Column(BigInteger, ForeignKey('users.id'))
    dropped_at = Column(DateTime, default=datetime.utcnow())
    bid_message_channel_id = Column(BigInteger)
    bid_message_id = Column(BigInteger)
    is_awarded = Column(Boolean, default=False)
    awarded_at = Column(DateTime)
    winner_id = Column(BigInteger, ForeignKey('characters.id'))
    winner_pr = Column(Numeric)
    winner_gp = Column(Integer)
    item = relationship('Item')
    raid = relationship('Raid')
    winner = relationship('Character')
    created_by = relationship('User')

    def award(self, session):
        try:
            if self.bids:
                bid_100_list = []
                bid_25_list = []
                bid_0_list = []

                for bid in self.bids:
                    if bid.bid_100:
                        bid_100_list.append(bid)
                    if bid.bid_25:
                        bid_25_list.append(bid)
                    if bid.bid_0:
                        bid_0_list.append(bid)

                if bid_100_list:
                    sorted_bid_pr_list = self.prioritize_bids(session=session, bids=bid_100_list)
                elif bid_25_list:
                    sorted_bid_pr_list = self.prioritize_bids(session=session, bids=bid_25_list)
                elif bid_0_list:
                    sorted_bid_pr_list = self.randomize_bids(bids=bid_0_list)
                else:
                    logger.warning("No valid bids for item being awarded")
                    self.is_awarded = True
                    self.awarded_at = datetime.utcnow()
                    return
                logger.debug("Sorted bid w/ pr list: " + str(sorted_bid_pr_list))
                winning_bid = sorted_bid_pr_list[0][0]
                winning_bid_pr = sorted_bid_pr_list[0][1]
                self.winner_pr = winning_bid_pr
                self.winner = winning_bid.character

                if bid_100_list or bid_25_list:
                    self.winner_gp = self.item.gp(role=winning_bid.character.spec.role)
                    if not bid_100_list:
                        self.winner_gp = round(self.winner_gp * 0.25, 0)
                    gp_bucket = session.query(UserPointBucket).filter(
                        UserPointBucket.user == winning_bid.user,
                        UserPointBucket.team == self.raid.team,
                        UserPointBucket.raid_tier == self.raid.get_tier(),
                        UserPointBucket.point_type == PointTypes.GP
                    ).one()
                    gp_bucket.grant_points(
                        session=session,
                        delta_points=self.winner_gp,
                        raid=self.raid,
                        item_drop=self,
                        character=winning_bid.character
                    )
                else:
                    self.winner_gp = 0
            else:
                logger.warning("No bids for item being awarded. Letting it rot!")
            self.is_awarded = True
            self.awarded_at = datetime.utcnow()
        except Exception as e:
            logger.error("Failed to award item because " + str(e))
            session.rollback()
            raise e

    def prioritize_bids(self, session, bids):
        bid_pr_list = []
        try:
            for bid in bids:
                signup = session.query(Signup).filter(Signup.raid == self.raid, Signup.user == bid.user).one()
                ep_bucket = session.query(UserPointBucket).filter(
                    UserPointBucket.user == bid.user,
                    UserPointBucket.team == self.raid.team,
                    UserPointBucket.raid_tier == self.raid.get_tier(),
                    UserPointBucket.point_type == PointTypes.EP
                ).one()
                gp_bucket = session.query(UserPointBucket).filter(
                    UserPointBucket.user == bid.user,
                    UserPointBucket.team == self.raid.team,
                    UserPointBucket.raid_tier == self.raid.get_tier(),
                    UserPointBucket.point_type == PointTypes.GP
                ).one()
                priority = round((ep_bucket.get_points() / gp_bucket.get_points()), 2)
                bid.pr = priority
                bid_pr_list.append((bid, priority))
            return sorted(bid_pr_list, key=itemgetter(1), reverse=True)
        except Exception as e:
            logger.error("Couldn't prioritize bid list")
            session.rollback()
            raise e

    def randomize_bids(self, bids):
        bid_pr_list = []
        try:
            for bid in bids:
                roll = random.randint(0, 100)
                bid.pr = roll
                bid_pr_list.append((bid, roll))

            return sorted(bid_pr_list, key=itemgetter(1), reverse=True)
        except Exception as e:
            logger.error("Somehow failed to randomize the bids list because " + str(e))
            raise


class ItemDropBid(Base):
    __tablename__ = 'item_drop_bids'
    drop_id = Column(BigInteger, ForeignKey('item_drops.id'), primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), primary_key=True)
    character_id = Column(Integer, ForeignKey('characters.id'))
    bid_100 = Column(Boolean, default=False)
    bid_25 = Column(Boolean, default=False)
    bid_0 = Column(Boolean, default=False)
    pr = Column(Numeric)
    roll = Column(Integer)
    drop = relationship('ItemDrop', backref='bids')
    user = relationship('User')
    character = relationship('Character')


class Bids():
    class __Bids():
        def __init__(self):
            self.emoji_id_mappings = {
                'bid_100': -1,
                'bid_25': -1,
                'bid_0': -1,
            }

        def register(self, emoji_name, emoji_id):
            # logger.info("Registering bid reaction")
            if self.get(emoji_name) is None:
                raise KeyError
            else:
                # logger.debug("Setting self.emoji_id_mappings[" + emoji_name + "] to " + emoji_id)
                self.emoji_id_mappings[emoji_name] = emoji_id
                return

        def get(self, key):
            try:
                val = self.emoji_id_mappings[key]
            except KeyError:
                val = None
            finally:
                return val

    instance = None

    def __init__(self):
        if not Bids.instance:
            Bids.instance = Bids.__Bids()

    def register(self, emoji_name, emoji_id):
        self.instance.register(emoji_name, emoji_id)
        return

    def lookup(self, emoji_id):
        name = None
        for _name, _id in self.instance.emoji_id_mappings:
            if _id == emoji_id:
                name = _name
        return name

    def get_all(self):
        return self.instance.emoji_id_mappings

    def __getitem__(self, key):
        return self.instance.emoji_id_mappings.get(key)


class UserPointBucket(Base):
    __tablename__ = 'point_buckets'
    team_id = Column(Integer, ForeignKey('teams.id'), primary_key=True)
    raid_tier = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), primary_key=True)
    point_type = Column(Enum(PointTypes), primary_key=True)
    __point_value = Column(Integer)
    user = relationship('User')
    team = relationship('Team')

    def __str__(self):
        return str(self.__point_value)

    def get_points(self):
        return self.__point_value

    def init_points(self, session):
        try:
            if self.point_type == PointTypes.GP:
                if self.__point_value is not None:
                    old_value = self.__point_value
                    delta_points = BASE_GP - old_value
                else:
                    old_value = 0
                    delta_points = 0
                self.__point_value = new_value = BASE_GP
                _ledger_entry = GearPointLedgerEntry(
                    bucket=self,
                    transaction_type=PointTransactionTypes.INIT,
                    point_old_value=old_value,
                    point_delta=delta_points,
                    point_new_value=new_value,
                )
            elif self.point_type == PointTypes.EP:
                if self.__point_value is not None:
                    old_value = self.__point_value
                    delta_points = 0 - old_value
                else:
                    old_value = 0
                    delta_points = 0
                self.__point_value = new_value = 0
                _ledger_entry = EffortPointLedgerEntry(
                    bucket=self,
                    transaction_type=PointTransactionTypes.INIT,
                    point_old_value=old_value,
                    point_delta=delta_points,
                    point_new_value=new_value,
                )
            else:
                raise ValueError("Invalid PointType on bucket")
            session.add(_ledger_entry)
            session.commit
            return
        except Exception as e:
            # logger.error("Unable to initialize PointBucket because " + str(e))
            session.rollback()
            raise e

    def load_points(self, session, load_value):
        try:
            if self.point_type == PointTypes.GP:
                if self.__point_value is not None:
                    old_value = self.__point_value
                    delta_points = load_value - old_value
                else:
                    old_value = 0
                    delta_points = 0
                self.__point_value = load_value
                _ledger_entry = GearPointLedgerEntry(
                    bucket=self,
                    transaction_type=PointTransactionTypes.LOAD,
                    point_old_value=old_value,
                    point_delta=delta_points,
                    point_new_value=load_value,
                )
            elif self.point_type == PointTypes.EP:
                if self.__point_value is not None:
                    old_value = self.__point_value
                    delta_points = load_value - old_value
                else:
                    old_value = 0
                    delta_points = 0
                self.__point_value = load_value
                _ledger_entry = EffortPointLedgerEntry(
                    bucket=self,
                    transaction_type=PointTransactionTypes.LOAD,
                    point_old_value=old_value,
                    point_delta=delta_points,
                    point_new_value=load_value,
                )
            else:
                raise ValueError("Invalid PointType on bucket")
            session.add(_ledger_entry)
            return
        except Exception as e:
            # logger.error("Unable to initialize PointBucket because " + str(e))
            session.rollback()
            raise e

    def grant_points(self, session, delta_points, raid=None, item_drop=None, character=None):
        try:
            old_value = self.__point_value
            new_value = old_value + delta_points
            if self.point_type == PointTypes.GP:
                if new_value < BASE_GP:
                    new_value = BASE_GP
                    delta_points = new_value - old_value
                _ledger_entry = GearPointLedgerEntry(
                    bucket=self,
                    transaction_type=PointTransactionTypes.GRANT,
                    raid=raid,
                    item_drop=item_drop,
                    character=character,
                    point_old_value=old_value,
                    point_delta=delta_points,
                    point_new_value=new_value,
                    point_type=self.point_type
                )
            elif self.point_type == PointTypes.EP:
                _ledger_entry = EffortPointLedgerEntry(
                    bucket=self,
                    transaction_type=PointTransactionTypes.GRANT,
                    raid=raid,
                    point_old_value=old_value,
                    point_delta=delta_points,
                    point_new_value=new_value,
                    point_type=self.point_type
                )
            else:
                raise ValueError("Unrecognized point_type during grant")
            self.__point_value = new_value
            session.add(_ledger_entry)
            session.commit()
            return
        except Exception as e:
            # logger.error("Failed to grant " + str(delta_points) + " points to bucket " + str(self.user_id) + '.' + str(self.team_id) + '.' + str(self.raid_tier))
            session.rollback()
            raise e

    def decay_points(self, session, percent_decay):
        try:
            old_value = self.__point_value

            if 0 < percent_decay < 100:
                delta_points = old_value * (percent_decay / 100)
            else:
                raise ValueError("Invalid decay amount, must be between 0 and 100")

            new_value = old_value - delta_points

            if self.point_type == PointTypes.GP:
                if new_value < BASE_GP:
                    new_value = BASE_GP
                    delta_points = new_value - old_value

                _ledger_entry = GearPointLedgerEntry(
                    bucket=self,
                    transaction_type=PointTransactionTypes.DECAY,
                    point_old_value=old_value,
                    point_delta=delta_points,
                    point_new_value=new_value,
                    point_type=self.point_type
                )
            elif self.point_type == PointTypes.EP:
                _ledger_entry = EffortPointLedgerEntry(
                    bucket=self,
                    transaction_type=PointTransactionTypes.DECAY,
                    point_old_value=old_value,
                    point_delta=delta_points,
                    point_new_value=new_value,
                    point_type=self.point_type
                )
            else:
                raise ValueError("Unrecognized point_type during decay")
            self.__point_value = new_value
            session.add(_ledger_entry)
            session.commit()
            return
        except Exception as e:
            logger.error("Failed to decay points to bucket "
                         + str(self.user_id) + '.' + str(self.team_id) + '.' + str(self.raid_tier)
                         )
            session.rollback()
            raise e


class EffortPointLedgerEntry(Base):
    __tablename__ = 'effort_point_ledger_entries'
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    raid_tier = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    raid_id = Column(Integer, ForeignKey('raids.id'))
    character_id = Column(Integer, ForeignKey('characters.id'))
    transaction_type = Column(Enum(PointTransactionTypes), nullable=False)
    point_old_value = Column(Integer)
    point_delta = Column(Integer)
    point_new_value = Column(Integer)
    point_type = Column(Enum(PointTypes))
    user = relationship('User', viewonly=True)
    character = relationship('Character')
    team = relationship('Team', viewonly=True)
    raid = relationship('Raid')
    bucket = relationship('UserPointBucket')
    __table_args__ = (ForeignKeyConstraint(
        [user_id, team_id, raid_tier, point_type],
        [UserPointBucket.user_id, UserPointBucket.team_id, UserPointBucket.raid_tier, UserPointBucket.point_type]),
                      {})


class GearPointLedgerEntry(Base):
    __tablename__ = 'gear_point_ledger_entries'
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    team_id = Column(Integer, ForeignKey('teams.id'), nullable=False)
    raid_tier = Column(Integer, nullable=False)
    raid_id = Column(Integer, ForeignKey('raids.id'))
    character_id = Column(Integer, ForeignKey('characters.id'))
    transaction_type = Column(Enum(PointTransactionTypes), nullable=False)
    point_old_value = Column(Integer)
    point_delta = Column(Integer)
    point_new_value = Column(Integer)
    point_type = Column(Enum(PointTypes))
    item_drop_id = Column(BigInteger, ForeignKey('item_drops.id'))
    item_drop = relationship('ItemDrop')
    user = relationship('User', viewonly=True)
    character = relationship('Character', viewonly=True)
    team = relationship('Team', viewonly=True)
    raid = relationship('Raid', viewonly=True)
    bucket = relationship('UserPointBucket')
    __table_args__ = (ForeignKeyConstraint(
        [user_id, team_id, raid_tier, point_type],
        [UserPointBucket.user_id, UserPointBucket.team_id, UserPointBucket.raid_tier, UserPointBucket.point_type]),
                      {})


###
#   Begin initializers/seed methods for testing
###
# TODO: Move all of these to a tests file
def seedSpecs():
    session = Session()

    session.add_all([
        Spec(character_class=CharacterClass.Warrior, name="Tank", role=CharacterRoles.Tank,
             emoticon_name="epgp_warrior"),
        Spec(character_class=CharacterClass.Warrior, name="Melee", role=CharacterRoles.Melee,
             emoticon_name="epgp_warrior"),

        Spec(character_class=CharacterClass.Paladin, name="Tank", role=CharacterRoles.Tank,
             emoticon_name="epgp_paladin"),
        Spec(character_class=CharacterClass.Paladin, name="Healer", role=CharacterRoles.Healer,
             emoticon_name="epgp_paladin"),
        Spec(character_class=CharacterClass.Paladin, name="Melee", role=CharacterRoles.Melee,
             emoticon_name="epgp_paladin"),

        Spec(character_class=CharacterClass.Hunter, name="Ranged", role=CharacterRoles.Ranged,
             emoticon_name="epgp_hunter"),

        Spec(character_class=CharacterClass.Rogue, name="Melee", role=CharacterRoles.Melee, emoticon_name="epgp_rogue"),

        Spec(character_class=CharacterClass.Priest, name="Caster", role=CharacterRoles.Caster,
             emoticon_name="epgp_priest"),
        Spec(character_class=CharacterClass.Priest, name="Healer", role=CharacterRoles.Healer,
             emoticon_name="epgp_priest"),

        Spec(character_class=CharacterClass.Mage, name="Caster", role=CharacterRoles.Caster, emoticon_name="epgp_mage"),

        Spec(character_class=CharacterClass.Warlock, name="Caster", role=CharacterRoles.Caster,
             emoticon_name="epgp_warlock"),

        Spec(character_class=CharacterClass.Druid, name="Caster", role=CharacterRoles.Caster,
             emoticon_name="epgp_druid"),
        Spec(character_class=CharacterClass.Druid, name="Tank", role=CharacterRoles.Tank, emoticon_name="epgp_druid"),
        Spec(character_class=CharacterClass.Druid, name="Melee", role=CharacterRoles.Melee, emoticon_name="epgp_druid"),
        Spec(character_class=CharacterClass.Druid, name="Healer", role=CharacterRoles.Healer,
             emoticon_name="epgp_druid")
    ])
    session.commit()


def seedChars():
    session = Session()

    session.add_all([
        Character(name="Cawl", character_guild="TECHPRIEST EMPIRE", \
                  spec=session.query(Spec)
                  .filter(Spec.character_class == 'Priest')
                  .filter(Spec.name == 'Shadow')
                  .one(),
                  user_id=392490218001006592

                  )

    ])
    session.commit()


def seedUsers():
    session = Session()

    session.add_all([
        User(id=392490218001006592, discord_guild_id=643694621385293825, name="paintballr9003", display_name="Cawl")
    ])

    session.commit()


def seedTeams():
    session = Session()

    session.add_all([
        Team(name='Aesir', description='The OG Acab train'),
        Team(name='Vanir', description='Rollin\' with Bt-sizzle'),
    ])

    aesir = session.query(Team).filter(Team.name == 'Aesir').one()
    vanir = session.query(Team).filter(Team.name == 'Vanir').one()

    session.commit()


def seedRewardSchedules():
    session = Session()

    aesir = session.query(Team).filter(Team.name == 'Aesir').one()
    vanir = session.query(Team).filter(Team.name == 'Vanir').one()

    session.add_all([
        RewardSchedule(team=aesir, zone=RaidZone.MC, signin_interval=timedelta(minutes=10),
                       start_bonus=100, tick_bonus=50, end_bonus=100, tick_interval=timedelta(minutes=30),
                       duration=timedelta(minutes=90)),
        RewardSchedule(team=vanir, zone=RaidZone.MC, signin_interval=timedelta(minutes=10),
                       start_bonus=100, tick_bonus=50, end_bonus=100, tick_interval=timedelta(minutes=30),
                       duration=timedelta(minutes=120)),
        RewardSchedule(team=aesir, zone=RaidZone.ONY, signin_interval=timedelta(minutes=10),
                       start_bonus=100, tick_bonus=0, end_bonus=100, tick_interval=timedelta(minutes=30),
                       duration=timedelta(minutes=30)),
        RewardSchedule(team=vanir, zone=RaidZone.ONY, signin_interval=timedelta(minutes=10),
                       start_bonus=100, tick_bonus=0, end_bonus=100, tick_interval=timedelta(minutes=30),
                       duration=timedelta(minutes=30)),
        RewardSchedule(team=aesir, zone=RaidZone.BWL, signin_interval=timedelta(minutes=10),
                       start_bonus=100, tick_bonus=50, end_bonus=100, tick_interval=timedelta(minutes=30),
                       duration=timedelta(minutes=90)),
        RewardSchedule(team=vanir, zone=RaidZone.BWL, signin_interval=timedelta(minutes=10),
                       start_bonus=100, tick_bonus=50, end_bonus=100, tick_interval=timedelta(minutes=30),
                       duration=timedelta(minutes=120))
    ])
    session.commit()


def seedRaids():
    session = Session()

    aesir = session.query(Team).filter(Team.name == 'Aesir').one()

    session.add_all([
        Raid(team=aesir, zone=RaidZone.MC, starts_at=(datetime.now() + timedelta(days=3)))
    ])
    session.commit()


def seedSubclasses():
    session = Session()

    session.add_all([
        ItemSubClass(name="One Handed Axe", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Axe.value),
        ItemSubClass(name="Two Handed Axe", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Axe2.value),
        ItemSubClass(name="Bow", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Bow.value),
        ItemSubClass(name="Gun", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Gun.value),
        ItemSubClass(name="One Handed Mace", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Mace.value),
        ItemSubClass(name="Two Handed Mace", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Mace2.value),
        ItemSubClass(name="Polearm", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Polearm.value),
        ItemSubClass(name="One Handed Sword", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Sword.value),
        ItemSubClass(name="Two Handed Sword", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Sword2.value),
        ItemSubClass(name="Staff", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Staff.value),
        ItemSubClass(name="Exotic", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Exotic.value),
        ItemSubClass(name="Two Handed Exotic", item_class=ItemClasses.Weapon,
                     subclass_id=WeaponSubclasses.Exotic2.value),
        ItemSubClass(name="Fist Weapon", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Fist.value),
        ItemSubClass(name="Misc", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Misc.value),
        ItemSubClass(name="Dagger", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Dagger.value),
        ItemSubClass(name="Thrown Weapon", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Thrown.value),
        ItemSubClass(name="Spear", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Spear.value),
        ItemSubClass(name="Crossbow", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Crossbow.value),
        ItemSubClass(name="Wand", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Wand.value),
        ItemSubClass(name="Fishing Pole", item_class=ItemClasses.Weapon, subclass_id=WeaponSubclasses.Fishing.value),
        ItemSubClass(name="Piece of Misc Armor", item_class=ItemClasses.Armor,
                     subclass_id=0),
        ItemSubClass(name="Piece of Cloth Armor", item_class=ItemClasses.Armor,
                     subclass_id=ArmorSubclasses.Cloth.value),
        ItemSubClass(name="Piece of Leather Armor", item_class=ItemClasses.Armor,
                     subclass_id=ArmorSubclasses.Leather.value),
        ItemSubClass(name="Piece of Mail Armor", item_class=ItemClasses.Armor, subclass_id=ArmorSubclasses.Mail.value),
        ItemSubClass(name="Piece of Plate Armor", item_class=ItemClasses.Armor,
                     subclass_id=ArmorSubclasses.Plate.value),
        ItemSubClass(name="Shield", item_class=ItemClasses.Armor, subclass_id=ArmorSubclasses.Shield.value),
        ItemSubClass(name="Libram", item_class=ItemClasses.Armor, subclass_id=ArmorSubclasses.Libram.value),
        ItemSubClass(name="Idol", item_class=ItemClasses.Armor, subclass_id=ArmorSubclasses.Idol.value),
        ItemSubClass(name="Totem", item_class=ItemClasses.Armor, subclass_id=ArmorSubclasses.Totem.value),
        ItemSubClass(name="Consumable", item_class=ItemClasses.Consumable, subclass_id=0),
        ItemSubClass(name="Quest", item_class=ItemClasses.Quest, subclass_id=0)
    ])

    session.commit()


def seedItems():
    session = Session()

    thundersubclass = session.query(ItemSubClass).filter_by(item_class=ItemClasses.Weapon).filter_by(
        subclass_id=WeaponSubclasses.Sword.value).one()
    anasubclass = session.query(ItemSubClass).filter_by(item_class=ItemClasses.Weapon).filter_by(
        subclass_id=WeaponSubclasses.Staff.value).one()

    session.add_all([
        Item(
            id=19019,
            name="Thunderfury, Blessed Blade of the Windseeker",
            item_level=80,
            required_level=60,
            icon_url='https://render-classic-us.worldofwarcraft.com/icons/56/inv_sword_39.jpg',
            item_class=ItemClasses.Weapon,
            item_subclass=thundersubclass,
            quality='Legendary',
            inventory_type="WEAPON",
            inventory_type_name="One-Hand",
            max_count=1
        ),
        Item(
            id=18609,
            name="Anathema",
            item_level=75,
            required_level=60,
            icon_url="https://render-classic-us.worldofwarcraft.com/icons/56/inv_staff_12.jpg",
            item_class=ItemClasses.Weapon,
            item_subclass=anasubclass,
            quality='Epic',
            inventory_type="WEAPON",
            inventory_type_name="Two-Hand",
            max_count=1
        )
    ])

    session.commit()
