import os
import discord
import worker
import asyncio
import pytz
from lib.helpers import *
from datetime import datetime
from dateutil import parser
from operator import attrgetter, itemgetter
from constants import *
from models import Spec, Character, Team, Raid, User, PointTypes, UserPointBucket, EffortPointLedgerEntry, \
    GearPointLedgerEntry, ItemDrop, ItemDropBid, Bids

DISCORD_BOT_TOKEN = os.environ['DISCORD_BOT_TOKEN']
FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT)
logger = logging.getLogger('argbot')

client = discord.Client()

logger.debug("Checking for access to scheduler?")
logger.debug("Scheduler is " + str(worker.scheduler))


async def attach_signup_reactions(message):
    session = models.Session()
    logger.info("Attaching signup reactions to raid")
    try:
        for spec in session.query(Spec).all():
            logger.debug("Adding reaction " + spec.emoticon_name + ':' + str(spec.emoticon_id) + " for " + str(
                spec.character_class.name) + " to message id " + str(message.id))
            await message.add_reaction('<' + spec.emoticon_name + ':' + str(spec.emoticon_id) + '>')
    except Exception as e:
        logger.error("Failed to add reaction to raid_signup because: " + str(e))
        session.rollback()
        raise e
    finally:
        session.close()
        return


def configure_guild_emojis():
    logger.info("Configuring custom emojis")
    session = models.Session()
    try:
        emoji_list = client.emojis
        logger.debug("Got emoji list, starting iterations")
        for emoji in emoji_list:
            logger.debug("Starting iteration for " + str(emoji))
            specs = session.query(Spec).filter(Spec.emoticon_name == emoji.name).all()
            if specs:
                logger.debug("Updating specs " + str(specs) + " with emoji id ")
                for spec in specs:
                    spec.emoticon_id = emoji.id
            else:
                logger.info("Couldn't find spec, trying to register a bid instead for emoji named " + emoji.name)
                if emoji.name in ['bid_100', 'bid_25', 'bid_0']:
                    logger.debug("Registering bid emoji " + emoji.name + " " + str(emoji.id))
                    Bids().register(emoji.name, emoji.id)
                else:
                    logger.info("Couldn't register emoji: " + emoji.name + ':' + str(emoji.id))
        session.commit()
    except Exception as e:
        logger.error("Failed to load custom guild emojis because " + str(e))
        session.rollback()
        raise e
    finally:
        session.close()
        return


def configure_guild_channels():
    logger.info("Configuring team channels")
    session = models.Session()

    try:
        if len(client.guilds) == 1:
            guild = client.guilds[0]
        else:
            raise RuntimeError("Guild count mismatch!")
        channel_list = guild.voice_channels
        teams = session.query(Team).all()
        logger.info("Got channel list and teams, starting to process intersections.")
        for channel in channel_list:
            for team in teams:
                if team.name in channel.name:
                    logger.debug("Registering " + channel.name + ':' + str(channel.id) + " for team " + team.name)
                    team.voice_channel_id = channel.id
        session.commit()
        return
    except Exception as e:
        logger.error("Failed to configure voice channels because " + str(e))
        session.rollback()
        raise e
    finally:
        session.close()


def generate_drop_embed(item_drop):
    logger.info("Starting embed render for item drop " + str(item_drop.id))
    session = models.Session()
    try:
        if item_drop.bids:
            bids_100 = session.query(ItemDropBid).filter(ItemDropBid.drop == item_drop,
                                                         ItemDropBid.bid_100 == True).all()
            bids_25 = session.query(ItemDropBid).filter(ItemDropBid.drop == item_drop, ItemDropBid.bid_25 == True).all()
            bids_0 = session.query(ItemDropBid).filter(ItemDropBid.drop == item_drop, ItemDropBid.bid_0 == True).all()
        else:
            bids_100 = []
            bids_25 = []
            bids_0 = []

        val_100 = stringify_bids(bid_pr_list=item_drop.prioritize_bids(session=session, bids=bids_100))
        val_25 = stringify_bids(bid_pr_list=item_drop.prioritize_bids(session=session, bids=bids_25))

        bids_pr_0 = []
        if not item_drop.is_awarded:
            for bid in bids_0:
                bids_pr_0.append((bid, 0))
        elif item_drop.is_awarded and not (bids_100 or bids_25):
            for bid in sorted(bids_0, key=attrgetter('pr'), reverse=True):
                bids_pr_0.append((bid, bid.pr))

        val_0 = stringify_bids(bid_pr_list=bids_pr_0)

        embed = discord.Embed(title="**" + item_drop.item.name + "**", colour=item_to_quality_color(item_drop.item),
                              timestamp=item_drop.dropped_at)

        embed.set_thumbnail(url=item_drop.item.icon_url)
        embed.set_footer(text="Dropped in " + item_drop.raid.zone.name + " for " + item_drop.raid.team.name)
        embed.add_field(name="A " + item_drop.item.item_subclass.name, value="** **", inline=False)
        embed.add_field(name="Item Level: " + str(item_drop.item.item_level),
                        value="Base GP Value: " + str(item_drop.item.gp()), inline=False)
        embed.add_field(name="Upgrade Bids", value=val_100, inline=True)
        embed.add_field(name="Sidegrade Bids", value=val_25, inline=True)
        embed.add_field(name="Offspec/PVP Bids", value=val_0, inline=True)
        embed.set_footer(
            text="Drop created by " + item_drop.created_by.display_name + " | Drop ID: " + str(item_drop.id))
        if item_drop.is_awarded:
            if item_drop.winner:
                embed.add_field(name="Grats to",
                                value=item_drop.winner.name + " with " + str(item_drop.winner_pr) + " for " + str(
                                    item_drop.winner_gp) + " GP.")
            else:
                embed.add_field(name="Grats to", value="Asgardbank for their shiny new shard")
        return embed
    except Exception as e:
        logger.error("Failed to generate item_drop_embed because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
        raise e
    finally:
        session.close()


async def attach_itemdrop_bid_reactions(item_drop):
    channel = client.get_channel(item_drop.bid_message_channel_id)
    message = await channel.fetch_message(item_drop.bid_message_id)
    bids = Bids()
    for emoji_name in bids.get_all():
        reaction_string = '<' + emoji_name + ':' + str(bids[emoji_name]) + '>'
        logger.debug("Reaction string is " + reaction_string)
        await message.add_reaction(reaction_string)
    return


def render_help(user):
    help_text = ""
    # user_role_names = []
    logger.debug("Generating help message for user with roles " + str(user.roles))
    # for role in user.roles:
    #    user_role_names.append(role.name)
    for command in COMMAND_MAP:
        # if COMMAND_MAP[command]['required_role'] in user_role_names:
        if any(role.name == COMMAND_MAP[command]['required_role'] for role in user.roles):
            help_text += command + " - " + COMMAND_MAP[command]['description'] + "\r\n"
            help_text += "\t\tExample: " + COMMAND_MAP[command]['example'] + "\r\n"
    #  logger.debug("Sending back help text " + str(help_text))
    return help_text


@client.event
async def on_ready():
    logger.info('I am ready and logged in as {0}'.format(client.user))

    configure_guild_emojis()
    configure_guild_channels()


@client.event
async def on_message(message):
    if message.author == client.user:
        # Ignore messages from myself
        return
    elif message.content.startswith('arg.'):
        command = message.content.split(' ')[0]
        logger.debug("Looking for " + command + " in map")
        if COMMAND_MAP.get(command):
            logger.debug("Found command in map")
            if any(role.name == COMMAND_MAP[command]['required_role'] for role in message.author.roles):
                await COMMAND_MAP.get(command)['handler'](message)
            else:
                await message.channel.send("Access Denied: You do not possess the role required for that command.")
        else:
            await message.channel.send('Command Not Found, try arg.help for usage information')
    else:
        logger.debug("Message Contents: " + message.content)
    return


@client.event
async def on_raw_reaction_add(raw_event):
    session = models.Session()
    logger.debug("Full reaction event: " + str(raw_event))

    try:
        if raw_event.user_id != client.user.id:
            _raid = session.query(Raid).filter(Raid.signup_message_id == raw_event.message_id).one_or_none()
            if _raid is not None:
                logger.info("Found a raid!")
                await handle_reaction_raid(raw_event=raw_event, session=session, raid=_raid)
            else:
                logger.info("Searching for itemdrops")
                _itemdrop = session.query(ItemDrop).filter(
                    ItemDrop.bid_message_id == raw_event.message_id).one_or_none()
                if _itemdrop is not None:
                    logger.info("Found an itemdrop")
                    if not _itemdrop.is_awarded:
                        await handle_reaction_bid(raw_event=raw_event, session=session, item_drop=_itemdrop)
                    else:
                        logger.warning(
                            "Ignoring late bid from " + str(raw_event.user_id) + " for drop " + str(_itemdrop.id))
                        await send_dm(raw_event.user_id, "Recieved your bid after the item was already awarded, sorry!")
    except Exception as e:
        logger.error("Unable to process reaction because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
    finally:
        session.close()
        return


def confirm_signups(session, raid):
    logger.info("Processing signups for raid " + str(raid.id))
    try:
        logger.debug("Looking for channel " + str(raid.team.voice_channel_id))
        channel = client.get_channel(raid.team.voice_channel_id)
        member_ids = []
        for member in channel.members:
            member_ids.append(member.id)
        logger.debug("Channel member ids " + str(member_ids))

        for signup in raid.signups:
            if signup.user.id in member_ids:
                signup.confirm()
            else:
                logger.debug("User " + str(signup.user.id) + " not found in channel, not confirming")
        session.commit()
        return
    except Exception as e:
        logger.error("Couldn't confirm signups because " + str(e))
        session.rollback()
        raise e


def item_to_quality_color(item):
    quality = item.quality

    if quality == 'Legendary':
        color = discord.Colour(0xbd831c)
    elif quality == 'Epic':
        color = discord.Colour(0xa335ee)
    elif quality == 'Rare':
        color = discord.Colour(0x0070dd)
    elif quality == 'Uncommon':
        color = discord.Colour(0x1eff00)
    elif quality == 'Common':
        color = discord.Colour(0x000000)
    else:
        color = discord.Colour(0x000000)
    return color


@client.event
async def on_raw_reaction_remove(raw_event):
    session = models.Session()
    logger.debug("Full reaction event for removal: " + str(raw_event))

    try:
        if raw_event.user_id != client.user.id:
            _raid = session.query(Raid).filter(Raid.signup_message_id == raw_event.message_id).one_or_none()
            if _raid is not None:
                logger.info("Found a raid!")
                await handle_reaction_raid(raw_event=raw_event, session=session, raid=_raid)
            else:
                logger.info("Searching for itemdrops")
                _itemdrop = session.query(ItemDrop).filter(
                    ItemDrop.bid_message_id == raw_event.message_id).one_or_none()
                if _itemdrop is not None:
                    logger.info("Found an itemdrop")
                    if not _itemdrop.is_awarded:
                        await handle_reaction_bid(raw_event=raw_event, session=session, item_drop=_itemdrop)
                    else:
                        logger.warning(
                            "Ignoring late bid cancellation from " + str(raw_event.user_id) + " for drop " + str(
                                _itemdrop.id))
                        await send_dm(raw_event.user_id,
                                      "Received your bid cancellation after the item was already awarded."
                                      + " If you won the item, then don't equip it and ping a Raid Leader for help")
    except Exception as e:
        logger.error("Unable to process reaction because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
    finally:
        session.close()


def generate_pr_embed(session, team):
    logger.info("Generating PR embed for " + team.name)
    try:
        embed = discord.Embed(title="**" + team.name + "**", timestamp=datetime.utcnow())

        for raid_tier in models.ActiveRaidTiers:
            logger.debug("Getting buckets for " + raid_tier.name)
            bucket_tuples = []
            ep_buckets = session.query(UserPointBucket) \
                .filter(
                UserPointBucket.team == team,
                UserPointBucket.raid_tier == raid_tier.tier,
                UserPointBucket.point_type == PointTypes.EP
            ) \
                .all()
            for ep_bucket in ep_buckets:
                gp_bucket = session.query(UserPointBucket) \
                    .filter(
                    UserPointBucket.team == team,
                    UserPointBucket.raid_tier == raid_tier.tier,
                    UserPointBucket.point_type == PointTypes.GP,
                    UserPointBucket.user == ep_bucket.user
                ) \
                    .one()
                ep_val = ep_bucket.get_points()
                gp_val = gp_bucket.get_points()
                # TODO: REPLACE WITH COMMON BUCKET.CALCULATE_PR FUNCTION
                pr_val = round((ep_val / gp_val), 2)
                bucket_tuples.append((ep_bucket.user.display_name, ep_val, gp_val, pr_val))

            name_str = ""
            point_str = ""
            pr_str = ""
            pr_list = sorted(bucket_tuples, key=itemgetter(3), reverse=True)
            for entry in pr_list:
                name_str += entry[0] + "\r\n"
                point_str += str(entry[1]) + "\t/\t" + str(entry[2]) + " =\r\n"
                pr_str += str(entry[3]) + "\r\n"

            embed.add_field(name="**" + raid_tier.name + "**", value=name_str, inline=True)
            embed.add_field(name="** **", value=point_str, inline=True)
            embed.add_field(name="** **", value=pr_str, inline=True)
        return embed
    except Exception as e:
        logger.error("Unable to generate PR embed because: " + str(e))
        logger.error(traceback.format_exc())
        raise


async def send_dm(user_id, content=None, embed=None):
    try:
        _recipient = client.get_user(user_id)
        if embed:
            await _recipient.send(embed=embed)
        elif content:
            await _recipient.send(content=content)
        else:
            raise KeyError("No content to send via DM")
        return
    except Exception as e:
        logger.error("Unable to send a DM to user " + str(user_id) + " because " + str(e))
        logger.error(traceback.format_exc())


def process_rewards(raid_id):
    session = models.Session()

    try:
        raid = session.query(Raid).filter(Raid.id == raid_id).one()
        confirm_signups(session, raid)
        raid.reward(session)
    except Exception as e:
        logger.error("Failed to process rewards for raid " + str(raid.id) + " because " + str(e))
        raise
    try:
        if datetime.utcnow() < raid.ends_at:
            logger.debug("Setting up next process_rewards run at" + str(raid.ends_at))
            worker.scheduler.add_job(process_rewards,
                                     kwargs={'raid_id': raid.id},
                                     trigger='date',
                                     run_date=(datetime.utcnow() + raid.reward_schedule.tick_interval)
                                     )
        asyncio.run_coroutine_threadsafe(
            client.get_channel(raid.signup_message_channel_id)
                .send(content="Processed EP reward for Raid ID " + str(raid.id)),
            client.loop
        )
        return
    # TODO: Notify raid signup channel of awarded EP or failure
    except Exception as e:
        logger.error("Failed to schedule next reward for raid")
        logger.error(traceback.format_exc())
        asyncio.run_coroutine_threadsafe(
            client.get_channel(raid.signup_message_channel_id)
                .send(content="Failed to process reward for Raid ID " + str(raid.id)
                      ),
            client.loop
        )
        raise e
    finally:
        session.close()


def generate_raid_embed(raid):
    session = models.Session()
    logger.info("Attempting to generate embed object")
    title_str = (raid.team.name + " is going to " + raid.zone.name + " at " +
                 paint_time(raid.starts_at.astimezone(pytz.timezone(SERVER_TIMEZONE))))
    embed = discord.Embed(title=("**" + title_str + "**"), colour=discord.Colour(0x481fc8), description=raid.notes,
                          timestamp=datetime.now())

    try:
        _signup_characters = session.query(Signup) \
            .filter(Signup.raid == raid, Signup.is_rescinded == False) \
            .join(Signup.character) \
            .join(Character.spec) \
            .all()
        logger.debug("Got list of " + str(len(_signup_characters)) + " signup characters")

        _role_summary = {
            CharacterRoles.Tank: {
                "count": 0,
                "characters": []
            },
            CharacterRoles.Melee: {
                "count": 0,
                "characters": []
            },
            CharacterRoles.Ranged: {
                "count": 0,
                "characters": []
            },
            CharacterRoles.Caster: {
                "count": 0,
                "characters": []
            },
            CharacterRoles.Healer: {
                "count": 0,
                "characters": []
            }
        }
        _spec_summary = {}
        for spec in session.query(Spec).all():
            if _spec_summary.get(spec.character_class) is None:
                _spec_summary[spec.character_class] = {}
            _spec_summary[spec.character_class][spec.role] = {
                'count': 0,
                'characters': []
            }
        for signup_character_spec in _signup_characters:
            logger.info("Processing signup.")
            logger.debug("Character: " + str(signup_character_spec.character))
            _role_summary[signup_character_spec.character.spec.role]['count'] += 1
            _role_summary[signup_character_spec.character.spec.role]['characters'].append(
                signup_character_spec.character.name)
            _spec_summary[signup_character_spec.character.spec.character_class][
                signup_character_spec.character.spec.role][
                'count'] += 1
            _spec_summary[signup_character_spec.character.spec.character_class][
                signup_character_spec.character.spec.role][
                'characters'].append(signup_character_spec.character.name)

        logger.debug("Completed role summary: " + str(_role_summary))
        logger.debug("Completed spec summary: " + str(_spec_summary))

        # Change to zone-specific image URL from DB
        if raid.zone == RaidZone.ONY:
            embed.set_image(url="https://bnetcmsus-a.akamaihd.net/cms/blog_header/8g/8G9PJA14T3FN1566592377439.jpg")
        elif raid.zone == RaidZone.MC:
            embed.set_image(url="https://bnetcmsus-a.akamaihd.net/cms/blog_header/ni/NIS3DMMR209S1565217183624.jpg")
        elif raid.zone == RaidZone.BWL:
            embed.set_image(url="https://bnetcmsus-a.akamaihd.net/cms/blog_header/3x/3XXVYU3ATMOJ1581531399970.jpg")
        elif raid.zone == RaidZone.ZG:
            embed.set_image(url="")
        elif raid.zone == RaidZone.AQ20:
            embed.set_image(url="https://images.app.goo.gl/jxPYawFFDcjS9vEx7")
        elif raid.zone == RaidZone.AQ40:
            embed.set_image(url="https://images.app.goo.gl/dMjiYnT2vXzsu1ju6")
        elif raid.zone == RaidZone.NAXX:
            embed.set_image(url="")
        embed.set_footer(text="Event scheduled by " + raid.created_by.display_name + "\t|Raid ID:" + str(raid.id))
        embed.add_field(name="Total Signups " + str(len(_signup_characters)), value="** **", inline=False)
        embed.add_field(name=":shield: " + str(_role_summary[CharacterRoles.Tank].get('count')) + " - Melee - " + str(
            _role_summary[CharacterRoles.Melee].get('count')) + " :knife:",
                        value="** ** ** **", inline=True)
        embed.add_field(
            name=":bow_and_arrow: " + str(_role_summary[CharacterRoles.Ranged].get('count')) + " Ranged - " + str(
                _role_summary[CharacterRoles.Caster].get('count')) + " :zap:",
            value="** ** ** **", inline=True)
        embed.add_field(name="Heals - " + str(_role_summary[CharacterRoles.Healer].get('count')) + " :ambulance:",
                        value="** ** ** **", inline=True)

        embed.add_field(name="__**Tank**__ (" + str(_role_summary[CharacterRoles.Tank].get('count')) + ")",
                        value=fieldvalue_from_characters(_role_summary[CharacterRoles.Tank]['characters']), inline=True)
        embed.add_field(
            name="__**Hunter**__ (" + str(
                _spec_summary[CharacterClass.Hunter][CharacterRoles.Ranged].get('count')) + ")",
            value=fieldvalue_from_characters(_spec_summary[CharacterClass.Hunter][CharacterRoles.Ranged]['characters']),
            inline=True)
        embed.add_field(
            name="__**Priest**__ (" + str(
                _spec_summary[CharacterClass.Priest][CharacterRoles.Healer].get('count')) + ")",
            value=fieldvalue_from_characters(_spec_summary[CharacterClass.Priest][CharacterRoles.Healer]['characters']),
            inline=True)

        embed.add_field(
            name="__**Warrior**__ (" + str(
                _spec_summary[CharacterClass.Warrior][CharacterRoles.Melee].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Warrior][CharacterRoles.Melee].get('characters')),
            inline=True)
        embed.add_field(
            name="__**Mage**__ (" + str(_spec_summary[CharacterClass.Mage][CharacterRoles.Caster].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Mage][CharacterRoles.Caster].get('characters')),
            inline=True)
        embed.add_field(
            name="__**Healadin**__ (" + str(
                _spec_summary[CharacterClass.Paladin][CharacterRoles.Healer].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Paladin][CharacterRoles.Healer].get('characters')),
            inline=True)

        embed.add_field(
            name="__**Feral DPS**__ (" + str(
                _spec_summary[CharacterClass.Druid][CharacterRoles.Melee].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Druid][CharacterRoles.Melee].get('characters')),
            inline=True)
        embed.add_field(
            name="__**Boomkin**__ (" + str(
                _spec_summary[CharacterClass.Druid][CharacterRoles.Caster].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Druid][CharacterRoles.Caster].get('characters')),
            inline=True)
        embed.add_field(
            name="__**Resto**__ (" + str(
                _spec_summary[CharacterClass.Druid][CharacterRoles.Healer].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Druid][CharacterRoles.Healer].get('characters')),
            inline=True)

        embed.add_field(
            name="__**Rogue**__ (" + str(_spec_summary[CharacterClass.Rogue][CharacterRoles.Melee].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Rogue][CharacterRoles.Melee].get('characters')),
            inline=True)
        embed.add_field(
            name="__**Warlock**__ (" + str(
                _spec_summary[CharacterClass.Warlock][CharacterRoles.Caster].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Warlock][CharacterRoles.Caster].get('characters')),
            inline=True)
        embed.add_field(name="** **", value="** **", inline=True)

        embed.add_field(
            name="__**Ret Paladin**__ (" + str(
                _spec_summary[CharacterClass.Paladin][CharacterRoles.Melee].get('count')) + ")",
            value=fieldvalue_from_characters(
                _spec_summary[CharacterClass.Paladin][CharacterRoles.Melee].get('characters')),
            inline=True)
        embed.add_field(
            name="__**Shadow Priest**__ (" + str(
                _spec_summary[CharacterClass.Priest][CharacterRoles.Caster].get('count')) + ")",
            value=fieldvalue_from_characters(_spec_summary[CharacterClass.Priest][CharacterRoles.Caster]['characters']),
            inline=True)
        embed.add_field(name="** **", value="** **", inline=True)

        return embed
    except Exception as e:
        logger.error("Failed to generate raid embed because " + str(e))
        logger.error(traceback.format_exc())
        raise e
    finally:
        session.close()


async def send_registration_help(user_id):
    help_msg = "Please check your registration command. " \
               + "It should be in the format 'arg.register CharacterName Role Class'\r\n"
    help_msg += "**Valid Role and Class combinations are:** \r\n"
    help_msg += "Tank (Druid, Warrior, or Paladin)\r\n"
    help_msg += "Melee (Druid, Paladin, Rogue, or Warrior)\r\n"
    help_msg += "Caster (Druid, Mage, Warlock, or Priest)\r\n"
    help_msg += "Healer (Druid, Priest, or Paladin)\r\n"
    help_msg += "Ranged (Hunter)\r\n"
    await send_dm(user_id, help_msg)
    return


async def handle_registercharacter(message):
    session = models.Session()
    logger.info("Starting character create")
    try:
        logger.debug("Starting user lookup")
        _user = session.query(User).filter(User.id == message.author.id).one_or_none()
        logger.debug("Starting team lookups")
        _team_aesir = session.query(Team).filter(Team.name == TEAM_NAME_ALPHA).one()
        _team_vanir = session.query(Team).filter(Team.name == TEAM_NAME_ONE).one()
        arg_array = parse_message_args(message.content)

        logger.debug("arg_array is " + str(len(arg_array)) + " entries long.")
        if len(arg_array) < 3:
            await send_registration_help(message.author.id)
        elif len(arg_array) == 3:
            logger.debug("Two argument character registration. Let's hope its a warlock, mage, or hunter")
            char_name = arg_array[1].title()
            spec_name = arg_array[2].title()
            try:
                specs = session.query(Spec).filter(Spec.character_class == CharacterClass[spec_name]).all()
                if len(specs) > 1:
                    error_body = "Registration Failed! Multiple specs found: \r\n"
                    for spec in specs:
                        if spec.name is not None:
                            error_body += spec.name + " "
                            error_body += spec.character_class + '\r\n'
                    error_body += "Please be more specific with your role and class."
                    await send_dm(user_id=message.author.id, content=error_body)
                elif len(specs) == 1:
                    spec = specs[0]
                else:
                    await send_registration_help(message.author.id)
            except Exception as e:
                logger.error("Unable to find spec for new character registration because: " + str(e))
                session.rollback()
                await send_registration_help(message.author.id)
                raise
        elif len(arg_array) == 4:
            logger.debug("Three argument character create")
            char_name = arg_array[1].title()
            char_spec = arg_array[2].title()
            char_class = arg_array[3].title()

            try:
                logger.debug("Search parameters= char_spec='" + str(char_spec) + "' and char_class='" + str(char_class))
                spec = session.query(Spec).filter(Spec.name.ilike(char_spec),
                                                  Spec.character_class == CharacterClass[char_class]).one()
            except Exception as e:
                logger.error("Unable to find spec for character registration because " + str(e))
                await send_registration_help(message.author.id)
                session.rollback()
                raise
        else:
            await send_registration_help(message.author.id)
            return
        if _user is None:
            logger.debug("User not found, creating anew.")
            _user = User(id=message.author.id,
                         discord_guild_id=message.author.guild.id,
                         name=message.author.name,
                         display_name=message.author.display_name)
            session.add(_user)

        if spec is not None:
            duplicate_characters = _user.find_characters(session=session,
                                                         character_class=spec.character_class,
                                                         )
            if duplicate_characters:
                logger.error("Found duplicate character when registering spec id "
                             + str(spec.id) + " for user " + str(_user.display_name))
                await send_dm(message.author.id,
                              "Already found a character registered to you with that class and spec." +
                              " If you are trying to change specs, contact Cawl for help (self-help coming soon!)")
            else:
                _character = Character(name=char_name, spec=spec, user=_user)
                logger.debug("Creating new character " + _character.name + " for " + str(_user.id))
                session.add(_character)
                session.commit()
                await message.channel.send("Character registration for " + str(_character) + " successful.")
                logger.info("Attempting auto-registration with teams for user " + str(_user.id))
                for _discord_role in message.author.roles:
                    if _discord_role.name == TEAM_NAME_ALPHA:
                        logger.debug("Found " + TEAM_NAME_ALPHA + " in roles for user " + str(_user.id))
                        _team_aesir.assign(session, _character)
                        await message.channel.send("Automatic Team Registration for " + TEAM_NAME_ALPHA
                                                   + " succeeded as well.")
                    if _discord_role.name == TEAM_NAME_ONE:
                        logger.debug("Found " + TEAM_NAME_ONE + " in roles for user " + str(_user.id))
                        _team_vanir.assign(session, _character)
                        await message.channel.send("Automatic Team Registration for " + TEAM_NAME_ONE
                                                   + " succeeded as well.")
                session.commit()
        return
    except Exception as e:
        logger.error("Failed to register character because : " + str(e))
        logger.error(traceback.format_exc())
        await message.channel.send("Registration failed.")
    finally:
        session.close()
        return


async def handle_whois(message):
    session = models.Session()
    _search_param = parse_message_args(message.content)[1]
    try:
        found_user = search_user(session, _search_param)

        _description = "Member of "
        raw_teams = []
        for character in found_user.characters:
            for team in character.rosters:
                raw_teams.append(team)
        teams = list(set(raw_teams))  # Forcing a typecast to set removes duplicate values
        # TODO: Remove User Level Team list and instead tag each character in the list with A or V
        if len(teams) >= 1:
            _description += teams[0].name
        if len(teams) == 2:
            _description += " & " + teams[1].name

        _embed = discord.Embed(title=found_user.display_name, description=_description, timestamp=datetime.utcnow())

        _characters_val = ""
        for character in session.query(Character).filter(Character.user == found_user).all():
            _characters_val += str(character.name) + '\t' + str(character.spec.name) + '\t' + str(
                character.spec.character_class.name) + ' \r\n'

        _embed.add_field(name="Characters", value=_characters_val, inline=False)

        for team in teams:
            _team_val = ""
            for tier_tuple in ActiveRaidTiers:
                _team_val += '__' + tier_tuple.name + '__' + '\r\n'
                _ep_val = session.query(UserPointBucket) \
                    .filter(
                    UserPointBucket.user == found_user,
                    UserPointBucket.team == team,
                    UserPointBucket.raid_tier == tier_tuple.tier,
                    UserPointBucket.point_type == PointTypes.EP
                ) \
                    .one()
                _team_val += ("EP:\t" + str(_ep_val) + '\r\n')
                _gp_val = session.query(UserPointBucket) \
                    .filter(
                    UserPointBucket.user == found_user,
                    UserPointBucket.team == team,
                    UserPointBucket.raid_tier == tier_tuple.tier,
                    UserPointBucket.point_type == PointTypes.GP
                ) \
                    .one()
                _team_val += ("GP:\t" + str(_gp_val) + '\r\n')
                _team_val += "** ** \r\n"
            _embed.add_field(name='**' + team.name + '**', value=_team_val, inline=True)

        await message.channel.send(embed=_embed)
    except Exception as e:
        logger.error('Failed to handle whois because : ' + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
        await message.channel.send('Failed to find character.')
    finally:
        session.close()
        return


async def handle_raidshow(message):
    session = models.Session()
    try:
        embed = discord.Embed(timestamp=datetime.utcnow())
        logger.info('Searching for active raids')
        raidsnow = session.query(Raid) \
            .filter(
            Raid.starts_at <= datetime.utcnow(),
            Raid.ends_at > datetime.utcnow()
        ) \
            .all()
        logger.debug("Active raids found: " + str(raidsnow))
        # response_body = ">>> **Current Raids** \r\n"
        raidsnow_val = ""
        if raidsnow:
            logger.debug('Found a raidsnow')
            for raid in raidsnow:
                channel = client.get_channel(raid.signup_message_channel_id)
                message = await channel.fetch_message(raid.signup_message_id)
                raidsnow_val += "\t-\t" + (
                    "[" + raid.team.name + " raiding " + raid.zone.name + " until "
                    + paint_time(
                        raid.ends_at.astimezone(pytz.timezone(SERVER_TIMEZONE))
                        )
                    + "](" + message.jump_url + ")\r\n"
                    )
        else:
            raidsnow_val = "No active raids"
        embed.add_field(name="**Active Raids**", value=raidsnow_val, inline=False)
        try:
            raidnext_val = ""
            for team in session.query(Team).all():
                try:
                    raidnext = session.query(Raid).filter(Raid.starts_at >= datetime.utcnow(),
                                                          Raid.team == team).order_by(Raid.starts_at.asc()).first()
                    if raidnext:
                        channel = client.get_channel(raidnext.signup_message_channel_id)
                        message = await channel.fetch_message(raidnext.signup_message_id)
                        raidnext_val += (
                            "[" + raidnext.team.name + " is going to " + raidnext.zone.name + " at "
                            + paint_time(raidnext.starts_at.astimezone(pytz.timezone(SERVER_TIMEZONE)))
                            + "](" + message.jump_url + ")\r\n"
                            )
                    else:
                        raidnext_val = '\t' + team.name + ' none found\r\n'
                except Exception as e:
                    logger.error("Failed to add raidnext because " + str(e))
                    session.rollback()
            embed.add_field(name="**Upcoming Raids**", value=raidnext_val, inline=False)
        except Exception as e:
            session.rollback()
            logger.error('handle_raidshow: Failed to load the list of teams')
            await send_dm(user_id=message.author.id, content=" Failed to load team list \r\n")
        await message.channel.send(embed=embed)
    except Exception as e:
        logger.error("Failed to send raidshow response because : " + str(e))
        logger.error(traceback.format_exc())
    finally:
        session.close()
        return


async def handle_raidschedule(message):
    # arg.raid.schedule aesir mc 2019-02-20 06:00 PM
    session = models.Session()
    logger.info("Processing new raid")
    try:
        arg_array = parse_message_args(message.content)
        _team_arg = arg_array[1]
        _zone_arg = arg_array[2]
        _start_datetime_arg = arg_array[3:]
        try:
            _team = session.query(Team).filter(Team.name.ilike(_team_arg)).one()
        except Exception as e:
            logger.error("Unable to find team")
            await message.channel.send("Raid Create Failed: Unable to locate team with name " + _team_arg)
            raise e
        try:
            _zone = RaidZone[_zone_arg.upper()]
        except Exception as e:
            logger.error("Unable to find raid zone")
            await message.channel.send("Raid Create Failed: Unable to locate zone with name " + _zone_arg.upper())
            raise e
        try:
            start_datetime = pytz.timezone(SERVER_TIMEZONE).localize(parser.parse(' '.join(_start_datetime_arg)))
            logger.debug("Read start_datetime as " + str(paint_time(start_datetime)))
        except Exception as e:
            logger.error(
                "Unable to parse raid start time '" + str(_start_datetime_arg) + "' because: " + str(e))
            logger.error(traceback.format_exc())
            await message.channel.send("Raid Create Failed: Unable to parse start date or time")
            raise e
        try:
            logger.info("Creating new raid")
            _new_raid = Raid(team=_team, zone=_zone, starts_at=start_datetime.astimezone(pytz.utc),
                             created_by_id=message.author.id)
            session.add(_new_raid)
            session.commit()
            _new_raid.ends_at = _new_raid.starts_at + _new_raid.reward_schedule.duration

            logger.info("Generating embed from raid")
            _embed = generate_raid_embed(_new_raid)
            logger.info("Sending signup message")
            _signup_message = await message.channel.send(embed=_embed)
            logger.info("Updating new raid's attached message id")
            _new_raid.signup_message_id = _signup_message.id
            _new_raid.signup_message_channel_id = _signup_message.channel.id
            session.commit()
            await attach_signup_reactions(_signup_message)

            logger.debug("Scheduling process_rewards job to run at " + str(_new_raid.starts_at))
            worker.scheduler.add_job(process_rewards,
                                     kwargs={'raid_id': _new_raid.id},
                                     trigger='date',
                                     run_date=_new_raid.starts_at
                                     # TODO: ADD SIGNUP DURATION TO STARTS_AT FOR RUN_DATE
                                     )
            session.commit()
        except Exception as e:
            logger.error("Unable to save raid because: " + str(e))
            logger.error(traceback.format_exc())
            await message.channel.send("Raid Create Failed: Unable to save")
            if _signup_message is not None:
                await _signup_message.delete()
            raise e
    except Exception as e:
        logger.error("Raid schedule operation failed because: " + str(e))
        session.rollback()
        if _signup_message is not None:
            await _signup_message.delete
    finally:
        session.close()
        return


async def handle_itemsearch(message):
    session = models.Session()

    try:
        item_name = message.content.split(' ', 1)[1]
        logger.debug('Searching for item named "' + str(item_name))
        if len(item_name) < 3:
            logger.warning('Ignoring item query with less than 3 characters :"' + item_name)
            await message.channel.send('Please use a longer word to search (>=3 characters)')
        else:
            try:
                items = session.query(Item).filter(Item.name.ilike('%' + item_name + '%')).all()
                if len(items) > 1:
                    response_body = ">>>| ** Too many similar Item Names Found** |\r\n"
                    for other_item in items:
                        response_body += "|" + other_item.name + "|\r\n"
                    await message.channel.send(response_body)
                elif len(items) == 1:
                    await message.channel.send(">>> " + str(items[0]))
                    # TODO: Unify item render to an embed with same details as raid_drop
            except:
                session.rollback()
                raise
    except Exception as e:
        await message.channel.send('Failed to search item')
        logger.error("Failed to search for item because : " + str(e))
    finally:
        session.close()
        return


async def handle_raidgrant(message):
    logger.info("Handling raid.grant")
    session = models.Session()
    try:
        arg_array = parse_message_args(message.content)

        logger.debug("arg_array is " + str(len(arg_array)) + " entries long.")
        if len(arg_array) != 3:
            logger.warning('Ignoring grant with improper arguments :"' + str(arg_array))
            await message.channel.send('Please use the correct format arg.raid.grant raid_id amount')
        if len(arg_array) == 3:
            logger.info("Looking for raid to grant to")
            raid_arg = arg_array[1]
            logger.info("Passed raid_arg")
            amount_arg = arg_array[2]
            logger.debug("Raid query param is " + str(raid_arg))
            _raid = session.query(Raid).filter(Raid.id == int(raid_arg)).one_or_none()
            if _raid is None:
                logger.info("Couldn't find raid by id.  Attempting to lookup by message id")
                _raid = session.query(Raid).filter(Raid.signup_message_id == int(raid_arg)).one_or_none()

            if _raid is not None:
                logger.info("Looking for active signups for raid to call give_effort")
                _active_signups = session.query(Signup).filter(Signup.raid == _raid, Signup.is_confirmed == True,
                                                               Signup.is_ejected == False).all()
                if not _active_signups:
                    logger.warning("No confirmed and non-ejected signups found for raid.")

                for _signup in _active_signups:
                    logger.info(
                        "Calling give_effort for signup id " + str(_signup.id) + " in the amount of "
                        + str(int(amount_arg))
                    )
                    _signup.give_effort(session=session, effort_amount=int(amount_arg))
                    logger.info("Completed give_effort for signup id " + str(_signup.id))
            else:
                logger.info("Unable to find any raids matching grant request")
                await message.channel.send("Unable to locate any raids with that identifier")
    except Exception as e:
        logger.error("Unable to finish raidgrant because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
    finally:
        session.close()
        return


async def handle_raiddrop(message):
    logger.info("Handling raid.drop")
    session = models.Session()
    try:
        arg_array = parse_message_args(message.content)

        logger.debug("arg_array is " + str(len(arg_array)) + " entries long.")
        if len(arg_array) != 3:
            await message.channel.send('Please use the correct format arg.raid.drop raid_id Item Name')
        else:
            logger.info("Looking for raid to drop item for")
            raid_arg = arg_array[1]
            item_name_arg = arg_array[2:]
            _item_name = ' '.join(item_name_arg)
            logger.debug("Item name param is " + str(_item_name))
            logger.debug("Raid query param is " + str(raid_arg))
            _raid = session.query(Raid).filter(Raid.id == int(raid_arg)).one_or_none()
            if _raid is None:
                logger.info("Couldn't find raid by id.  Attempting to lookup by message id")
                _raid = session.query(Raid).filter(Raid.signup_message_id == int(raid_arg)).one_or_none()
            if _raid is not None:
                logger.info("Found a raid, starting search for item")
                _items = session.query(Item).filter(Item.name.ilike(_item_name + '%')).all()
                # Maybe use HandleItemSearch()?
                if _items is None:
                    await message.channel.send("Unable to locate item with name " + str(_item_name))
                elif len(_items) == 1:
                    logger.info("Found a single item. Starting drop processing")
                    _created_by = session.query(User).filter(User.id == message.author.id).one()
                    _new_drop = ItemDrop(item=_items[0], raid=_raid, dropped_at=datetime.utcnow(),
                                         created_by=_created_by)
                    session.add(_new_drop)
                    session.commit()
                    _embed = generate_drop_embed(_new_drop)
                    logger.info("Sending itemdrop embed.")
                    _drop_message = await message.channel.send(embed=_embed)
                    _new_drop.bid_message_channel_id = _drop_message.channel.id
                    _new_drop.bid_message_id = _drop_message.id
                    await attach_itemdrop_bid_reactions(_new_drop)
                    session.commit()
                else:
                    logger.warning("More than one item found for drop; returning error")
                    await message.channel.send("Located too many items with name " + str(_item_name))
            return
    except Exception as e:
        logger.error("Unable to process drop because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
        if _drop_message is not None:
            await _drop_message.delete()
        await message.channel.send("Unable to process drop.")
    finally:
        session.close()
        return


async def handle_droprefresh(message):
    logger.info("Handling drop.refresh")
    session = models.Session()
    try:
        arg_array = parse_message_args(message.content)
        _drop_id_arg = arg_array[1]

        _item_drop = session.query(ItemDrop).filter(ItemDrop.id == _drop_id_arg).one()
        _embed = generate_drop_embed(_item_drop)
        channel = client.get_channel(_item_drop.bid_message_channel_id)
        message = await channel.fetch_message(_item_drop.bid_message_id)
        await message.edit(embed=_embed)
    except Exception as e:
        logger.error("Failed to refresh item embed because: " + str(e))
        session.rollback()
    finally:
        session.close()
        return


async def handle_raidconfirm(message):
    logger.info("Processing raidconfirm")
    session = models.Session()
    try:
        _arg_array = parse_message_args(message.content)
        _raid_id_arg = _arg_array[1]
        _raid = session.query(Raid).filter(Raid.id == int(_raid_id_arg)).one()
        if _raid is not None:
            if not _raid.is_closed:
                confirm_signups(session=session, raid=_raid)
                session.commit()
        return
    except Exception as e:
        logger.error("Failed to handle raid.confirm because " + str(e))
        session.rollback()
        await message.channel.send("Failed to process confirmations.")
        raise e
    finally:
        session.close()


async def handle_dropaward(message):
    logger.info("Processing drop award")
    session = models.Session()
    try:
        _arg_array = parse_message_args(message.content)
        _drop_id_arg = _arg_array[1]
        try:
            # TODO: refactor: split function here
            _item_drop = session.query(ItemDrop).filter(ItemDrop.id == int(_drop_id_arg)).one()
            if not _item_drop.is_awarded:
                _item_drop.award(session=session)
                session.commit()
                if _item_drop.winner_id is not None:
                    await message.channel.send("Item successfully awarded")
                else:
                    await message.channel.send("No bids, item is headed to shardsville")
            else:
                await message.channel.send("Item already awarded.  Check or refresh the drop id?")
        except Exception as e:
            logger.error("Failed to handle drop award because " + str(e))
            await message.channel.send("Failed to process item award.")
            session.rollback()
            raise e
        try:
            _embed = generate_drop_embed(_item_drop)
            _drop_channel = client.get_channel(_item_drop.bid_message_channel_id)
            _drop_message = await _drop_channel.fetch_message(_item_drop.bid_message_id)
            await _drop_message.edit(embed=_embed)
        except Exception as e:
            logger.error("Failed to update drop with award info because " + str(e))
            logger.error(traceback.format_exc())
            await message.channel.send(
                "Failed to update drop render in discord, but item was awarded.  Try arg.drop.refresh DropID to recover")
    except:
        logger.error(traceback.format_exc())
    finally:
        session.close()
        return


async def handle_raideject(message):
    logger.info("Processing raid ejection")
    session = models.Session()
    try:
        _arg_array = parse_message_args(message.content)
        _raid_id_arg = _arg_array[1]
        _person_arg = _arg_array[2]

        _user = search_user(session, _person_arg)
        if _user is not None:
            _signup = session.query(Signup).filter(Signup.raid_id == int(_raid_id_arg)).join(Signup.character).filter(
                Character.user == _user).one()
        else:
            logger.warning("Unable to find user for ejection")
            raise
        _signup.is_ejected = True
        _signup.ejected_at = datetime.utcnow()
        session.commit()
        return
    except Exception as e:
        logger.error("Failed to eject user because " + str(e))
        logger.error(traceback.format_exc())
        await send_dm(message.author.id, "Failed to eject " + str(_person_arg) + " from raid.")
        session.rollback()
    finally:
        session.close()


async def handle_useraudit(message):
    logger.info("Processing user audit request")
    session = models.Session()
    try:
        _arg_array = parse_message_args(message.content)
        person_arg = _arg_array[1]
        team_arg = _arg_array[2]

        _user = search_user(session, person_arg)
        _team = session.query(Team).filter(Team.name.ilike(team_arg)).one()

        if _user:
            _ep_transactions = {}
            for tier_tuple in models.ActiveRaidTiers:
                
                
                _ep_transactions[tier_tuple.name] = session.query(EffortPointLedgerEntry) \
                    .filter(EffortPointLedgerEntry.team == _team,
                            EffortPointLedgerEntry.user == _user,
                            EffortPointLedgerEntry.raid_tier == tier_tuple.tier) \
                    .order_by(EffortPointLedgerEntry.created_at.desc()) \
                    .all()  # Probably not how to do this. TODO: Lookup query.limit function
            _gp_transactions = {}
            for tier_tuple in models.ActiveRaidTiers:
                _gp_transactions[tier_tuple.name] = session.query(GearPointLedgerEntry) \
                    .filter(GearPointLedgerEntry.team == _team,
                            GearPointLedgerEntry.user == _user,
                            GearPointLedgerEntry.raid_tier == tier_tuple.tier) \
                    .order_by(EffortPointLedgerEntry.created_at.desc()) \
                    .all()
            # TODO Build a new embed formatter for the ledger entries
        return
    except Exception as e:
        logger.error("Couldn't process user audit request because " + str(e))
    finally:
        session.close()


async def handle_reaction_raid(raw_event, session, raid):
    try:
        _specs = session.query(Spec).filter(Spec.emoticon_id == raw_event.emoji.id).all()
        _user = session.query(User).filter(User.id == raw_event.user_id).one()
        action = raw_event.event_type

        _spec_ids = []
        for spec in _specs:
            _spec_ids.append(spec.id)

        _characters = session.query(Character).filter(Character.user == _user, Character.spec_id.in_(_spec_ids),
                                                      Character.rosters.contains(raid.team)).all()
        if not _characters:
            logger.error("Unable to find character for user id " + str(_user.id) + "and emoji id " + str(
                raw_event.emoji.id) + " for team " + str(raid.team.name))
            if action == 'REACTION_ADD':
                await send_dm(raw_event.user_id,
                              "Unable to find a character to sign up for this raid.  "
                              + "Are you using the correct class icon and checked your raid team assignment?")
        elif len(_characters) == 1:
            _signup = session.query(Signup).filter(Signup.user == _user, Signup.raid == raid).one_or_none()
            if action == 'REACTION_ADD':
                if _signup is None:
                    _signup = Signup(user=_user, character=_characters[0], raid=raid, signup_at=datetime.now())
                    session.add(_signup)
                else:
                    logger.info("Found existing signup id " + str(_signup.id) + " for this user for this raid")
                    if _signup.is_rescinded == True:  # Signup was previously rescinded, set back to active
                        _signup.is_rescinded = False
                        _signup.rescinded_at = datetime.utcnow()
                    _signup.character = _characters[0]  # Force to this current character regardless of old state
            elif action == 'REACTION_REMOVE':
                if _signup is not None and _signup.character == _characters[0]:
                    _signup.is_rescinded = True
                    _signup.rescinded_at = datetime.utcnow()
                else:
                    logger.warning("Couldn't find signup for removed reaction; I must've missed a REACTION_ADD event?")
            session.commit()
            _embed = generate_raid_embed(raid)
            channel = client.get_channel(raw_event.channel_id)
            message = await channel.fetch_message(raw_event.message_id)
            await message.edit(embed=_embed)
        else:
            logger.warning("More than one character found for signup.  Something is wrong")
            logger.debug(
                "Found characters " + str(_characters) + " for " + str(_user.id) + " with emoji " + str(
                    raw_event.emoji.id))
        return
    except Exception as e:
        logger.error("Unable to handle raid reaction because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()


async def handle_reaction_bid(raw_event, session, item_drop):
    logger.info("Handling item bid")
    try:
        try:
            _user = session.query(User).filter(User.id == raw_event.user_id).one()
            _signup = session.query(Signup).filter(Signup.user == _user, Signup.raid == item_drop.raid).one()
            action = raw_event.event_type
        except:
            await send_dm(raw_event.user_id,
                          "Unable to create your bid on " + item_drop.item.name + " because you aren't signed up for this raid.")
            raise

        if raw_event.emoji.name is None:
            logger.info("Emoji name was not included, looking it up from our registered cache")
            bid_name = Bids.lookup(raw_event.emoji.id)
        else:
            logger.debug("Got bid reaction name from event " + raw_event.emoji.name)
            bid_name = raw_event.emoji.name

        _item_drop_bid = session.query(ItemDropBid).filter(ItemDropBid.drop_id == item_drop.id,
                                                           ItemDropBid.user_id == _user.id).one_or_none()

        if _item_drop_bid is None:
            logger.info("Did not find existing bid; creating new one")
            _item_drop_bid = ItemDropBid(drop=item_drop, user=_user, character=_signup.character)
            session.add(_item_drop_bid)
        elif _item_drop_bid.character is None:
            # Bid was found, but character was not correctly attached before
            _item_drop_bid.character = _signup.character

        if bid_name == 'bid_100':
            if action == 'REACTION_ADD':
                _item_drop_bid.bid_100 = True
            elif action == 'REACTION_REMOVE':
                _item_drop_bid.bid_100 = False
        elif bid_name == 'bid_25':
            if action == 'REACTION_ADD':
                _item_drop_bid.bid_25 = True
            elif action == 'REACTION_REMOVE':
                _item_drop_bid.bid_25 = False
        elif bid_name == 'bid_0':
            if action == 'REACTION_ADD':
                _item_drop_bid.bid_0 = True
            elif action == 'REACTION_REMOVE':
                _item_drop_bid.bid_0 = False
        else:
            logger.error("Unknown bid name value when handling reaction " + str(bid_name))
        session.commit()

        try:
            _embed = generate_drop_embed(item_drop)
            channel = client.get_channel(raw_event.channel_id)
            message = await channel.fetch_message(raw_event.message_id)
            await message.edit(embed=_embed)
        except Exception as e:
            logger.error("Failed to update drop embed for " + str(item_drop.id) + " because " + str(e))
            await client.get_channel(raw_event.channel_id).send(
                "Unable to update latest bid info. Ask a GM to manually refresh")
            raise
    except Exception as e:
        logger.error("Unable to handle reaction bid because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()


async def handle_prwhisper(message):
    logger.info("Handling a PR request")
    session = models.Session()
    logger.debug("got a session")
    try:
        arg_array = message.content.split(' ')
        if len(arg_array) != 2:
            await send_dm(message.author.id, "arg.pr command requires a team name argument")
        logger.debug("Split the arg_array")
        team_arg = arg_array[1]

        try:
            logger.debug("Looking for team")
            team = session.query(Team).filter(Team.name.ilike(team_arg)).one()
        except Exception as e:
            logger.warning("Couldn't find team by name for PR whisper")
            await send_dm(message.author.id, "Couldn't find that team name. Check your spelling?")
            raise

        _embed = generate_pr_embed(session, team)
        await send_dm(user_id=message.author.id, embed=_embed)
        return
    except Exception as e:
        logger.error("Couldn't handle PR whisper because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
    finally:
        session.close()


async def handle_teamassign(message):
    # arg.team.assign aesir <@!1234567890> Cawl Healer Priest
    logger.info("Handling a team assignment")
    session = models.Session()
    try:
        arg_array = parse_message_args(message.content)
        if len(arg_array) == 3:
            team_arg = arg_array[1]
            char_arg = arg_array[2]
            logger.info("Trying to assign existing character with short arg_list")
            user_arg = None
            role_arg = None
            class_arg = None
        elif len(arg_array) == 6:
            logger.info("Processing character create")
            team_arg = arg_array[1]
            user_arg = arg_array[2]
            char_arg = arg_array[3]
            role_arg = arg_array[4]
            class_arg = arg_array[5]
        else:
            await send_dm(message.author.id, content="Unable to process assignment, invalid number of arguments.")
            raise ValueError("Invalid argument count provided to team.assign")

        try:
            logger.debug("Looking for team")
            team = session.query(Team).filter(Team.name.ilike(team_arg)).one()
        except Exception as e:
            logger.warning("Couldn't find team by name for assignment")
            await send_dm(message.author.id, "Couldn't find that team name. Check your spelling?")
            raise e

        if user_arg:
            try:
                logger.debug("Looking for user to assign character to")
                user = search_user(session, user_arg)
                if user is None:
                    logger.info("User not found, trying to create a new one.")
                    logger.debug("User arg looks like: " + str(user_arg))
                    if user_arg.startswith('<@!'):
                        new_user_id = user_arg.split('!')[1].replace('>', '')
                        logger.debug("Creating new user with id: " + str(new_user_id))
                        if len(message.mentions) == 1:
                            logger.info("Getting the user directly from the message's mention list")
                            discord_user = message.mentions[0]
                        else:
                            logger.info("Trying to fetch discord user from their API by ID")
                            discord_user = client.get_user(int(new_user_id))
                        logger.debug("Got user from discord: " + str(discord_user))
                        user = User(id=new_user_id,
                                    discord_guild_id=message.author.guild.id,
                                    name=discord_user.name,
                                    display_name=discord_user.display_name)
                        session.add(user)
                        session.commit()
                    else:
                        logger.warning("Unable to parse user")
                        raise ValueError("Unable to locate User")
            except Exception as e:
                logger.warning("Couldn't find or create discord user")
                await send_dm(message.author.id, "Couldn't find that discord user. Check your @tag to make sure it "
                              + "linked before you sent it?")
                raise e
        else:
            user = None
        try:
            logger.info("Searching for a character to assign")

            query = session.query(Character).filter(Character.name.ilike(char_arg))
            if user:
                query.filter(Character.user == user)
            try:
                character = query.one_or_none()
            except models.sqlalchemy.orm.exc.MultipleResultsFound as e:
                await send_dm(
                    (message.author.id, "Found more than one character with that name, ask Cawl for help"))

            if character:
                logger.info("Found an existing character, appending team to its rosters")
            elif user and role_arg and class_arg:
                logger.info("Role and class was provided, trying to create new character")
                try:
                    spec = session.query(Spec).filter(Spec.name.ilike(role_arg),
                                                      Spec.character_class == class_arg.title()).one()
                    character_list = user.find_characters(session=session, character_class=spec.character_class)
                    if len(character_list) == 1:
                        character = character_list[0]
                    elif len(character_list) > 1:
                        raise ValueError("Too many characters found with that class for this user.")

                    if not character:
                        logger.info("Creating new character for " + str(user))
                        character = Character(user=user, name=char_arg.title(), spec=spec)
                        session.add(character)
                except Exception as e:
                    await send_dm(message.author.id, "Couldn't find a spec matching " + str(role_arg) + ' '
                                  + str(class_arg) + '\r\n'
                                  + "Valid roles are Tank, Melee, Caster, Ranged, Healer\r\n")
                    raise e
            else:
                logger.warning("Unable to find character")
                await send_dm(message.author.id, "Couldn't find a character with name" + str(char_arg))
                raise ValueError("No character found with name" + char_arg)
            team.assign(session, character)
            session.commit()
        except Exception as e:
            logger.warning("Couldn't find or create character")
            # await send_dm(message.author.id, "Couldn't find or create that character")
            raise e

    except Exception as e:
        logger.error("Couldn't handle team assignment because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
    finally:
        session.close()


async def handle_usergrant(message):
    # arg.user.ep @User Team Tier Amount
    logger.info("Handling a user grant")
    session = models.Session()
    try:
        arg_array = parse_message_args(message.content)
        _point_type_arg = arg_array[0].split('.')[2]
        _user_arg = arg_array[1]
        _team_arg = arg_array[2]
        _tier_arg = arg_array[3]
        _amount_arg = arg_array[4]

        if _point_type_arg.lower() == 'ep':
            _point_type = PointTypes.EP
        elif _point_type_arg.lower() == 'gp':
            _point_type = PointTypes.GP
        else:
            raise ValueError("Invalid grant command, unknown point type")

        _user = search_user(session, _user_arg)

        if _user is None:
            raise ValueError("Couldn't locate user")

        _team = session.query(Team).filter(Team.name.ilike(_team_arg)).one()

        raid_tier = None
        for tier_tuple in ActiveRaidTiers:
            if _tier_arg.lower() in tier_tuple.name.lower():
                raid_tier = tier_tuple

        if raid_tier.tier is None:
            raise ValueError("Couldn't find that raid tier or we aren't tracking EPGP for it.")
        else:
            _bucket = session.query(UserPointBucket) \
                .filter(
                UserPointBucket.user == _user,
                UserPointBucket.team == _team,
                UserPointBucket.raid_tier == raid_tier.tier,
                UserPointBucket.point_type == _point_type
            ) \
                .one()
            _bucket.grant_points(
                session=session,
                delta_points=int(_amount_arg)
            )
        return
    except Exception as e:
        logger.error("Unable to process user grant because " + str(e))
        logger.error(traceback.format_exc())
        await message.channel.send("Unable to grant points to user")
        await send_dm(message.author.id, content="Unable to grant points to user because " + str(e))
        session.rollback()
    finally:
        session.close()


async def handle_decay(message):
    # arg.decay
    logger.info("Handling a user grant")
    session = models.Session()
    try:
        process_decayall(session)
        return
    except Exception as e:
        logger.error("Unable to process decay because " + str(e))
        logger.error(traceback.format_exc())
        session.rollback()
        await send_dm(message.author.id, content="Failed to execute decay because " + str(e))
    finally:
        session.close()


def process_decayall(session):
    for team in session.query(Team).all():
        for tier_tuple in ActiveRaidTiers:
            try:
                buckets = session.query(UserPointBucket).filter(
                    UserPointBucket.team == team,
                    UserPointBucket.raid_tier == tier_tuple.tier).all()
                for user_bucket in buckets:
                    user_bucket.decay_points(session=session, percent_decay=DECAY_PERCENT)
            except Exception as e:
                logger.error("Failed to process decay for " + str(team.name) + " tier " + str(tier_tuple.name))
                raise e
    session.commit()
    return


async def handle_help(message):
    logger.info("Handling a help request")
    await send_dm(message.author.id, render_help(message.author))
    return


COMMAND_MAP = {
    'arg.decay': {
        'handler': handle_decay,
        'description': "Apply decay to all groups",
        'example': "arg.decay",
        'required_role': GM_ROLE_NAME
    },
    'arg.drop.award': {
        'handler': handle_dropaward,
        'description': "Close and sort bids for a dropped item",
        'example': "arg.drop.award dropID",
        'required_role': GM_ROLE_NAME
    },
    'arg.drop.refresh': {
        'handler': handle_droprefresh,
        'description': "Force item drop bid list to refresh",
        'example': "arg.drop.refresh dropID",
        'required_role': GM_ROLE_NAME
    },
    'arg.help': {
        'handler': handle_help,
        'description': "Sends this help menu",
        'example': "arg.help",
        'required_role': EVERYONE_ROLE_NAME
    },
    'arg.item': {
        'handler': handle_itemsearch,
        'description': "Search for an Item",
        'example': "arg.item ItemName",
        'required_role': EVERYONE_ROLE_NAME
    },
    'arg.user.ep': {
        'handler': handle_usergrant,
        'description': "Give a single user an amount of EP",
        'example': "arg.user.ep @User TeamName TierNum Amount or arg.user.ep CharName TeamName RaidZone Amount",
        'required_role': GM_ROLE_NAME
    },
    'arg.user.gp': {
        'handler': handle_usergrant,
        'description': "Give a single user an amount of GP",
        'example': "arg.user.gp @User TeamName TierNum Amount or arg.user.gp CharName TeamName RaidZone Amount",
        'required_role': GM_ROLE_NAME
    },
    'arg.pr': {
        'handler': handle_prwhisper,
        'description': "Send the user an overview of the team's PR lists",
        'example': "arg.pr TeamName",
        'required_role': EVERYONE_ROLE_NAME
    },
    'arg.raids': {
        'handler': handle_raidshow,
        'description': "Show scheduled and active raids",
        'example': "arg.raids",
        'required_role': EVERYONE_ROLE_NAME
    },
    'arg.raid.confirm': {
        'handler': handle_raidconfirm,
        'description': "Confirm signed up members of the raid (via Discord VoIP connection)",
        'example': "arg.raid.confirm RaidID",
        'required_role': GM_ROLE_NAME
    },
    'arg.raid.drop': {
        'handler': handle_raiddrop,
        'description': "Post a dropped item to start the bidding process",
        'example': "arg.raid.drop RaidID ItemName",
        'required_role': GM_ROLE_NAME
    },
    'arg.raid.eject': {
        'handler': handle_raideject,
        'description': "Kicks member from the raid, halting EP gains until they sign back in",
        'example': "arg.raid.eject RaidID Name",
        'required_role': GM_ROLE_NAME
    },
    'arg.raid.grant': {
        'handler': handle_raidgrant,
        'description': "Gives EP to all confirmed members of a raid",
        'example': "arg.raid.grant RaidID Amount",
        'required_role': GM_ROLE_NAME
    },
    'arg.raid.schedule': {
        'handler': handle_raidschedule,
        'description': "Schedule and post signups for a new raid",
        'example': "arg.raid.schedule TeamName ZoneName StartsAt",
        'required_role': GM_ROLE_NAME
    },
    'arg.register': {
        'handler': handle_registercharacter,
        'description': "Create a new character for my user",
        'example': "arg.register CharName Role Class",
        'required_role': EVERYONE_ROLE_NAME
    },
    'arg.team.assign': {
        'handler': handle_teamassign,
        'description': "Create or assign a character to a team",
        'example': "arg.team.assign TeamName @User CharacterName Role Class",
        'required_role': GM_ROLE_NAME
    },
    'arg.whois': {
        'handler': handle_whois,
        'description': "Show someone else's ASGA:RD profile",
        'example': "arg.whois Name",
        'required_role': EVERYONE_ROLE_NAME
    }
}

if __name__ == "__main__":
    logger.setLevel(10)  # https://docs.python.org/2/library/logging.html#levels

    logger.info("Starting Discord Client")
    worker.scheduler.start()
    client.run(DISCORD_BOT_TOKEN)
    logger.info("Client ran")
