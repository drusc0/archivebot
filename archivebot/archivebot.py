"""A bot which downloads various files from chats."""
import os
from telethon import TelegramClient, events

from archivebot.config import config
from archivebot.subscriber import Subscriber
from archivebot.file import File
from archivebot.helper import (
    get_bool_from_text,
    get_chat_information,
    get_info_text,
    get_username,
    help_text,
    possible_media,
    session_wrapper,
    should_accept_message,
)
from archivebot.file_helper import (
    check_if_file_exists,
    get_channel_path,
    get_file_path,
)

NAME = config.TELEGRAM_BOT_API_KEY.split(':')[0]
archive = TelegramClient(NAME, config.TELEGRAM_APP_API_ID, config.TELEGRAM_APP_API_HASH)

# Ensure save directory for files exists
if not os.path.exists(config.TARGET_DIR):
    os.mkdir(config.TARGET_DIR)


@archive.on(events.NewMessage(pattern='/help'))
async def help(event):
    """Send a help text."""
    await event.respond(help_text)


@archive.on(events.NewMessage(pattern='/info'))
@session_wrapper()
async def info(event, session):
    """Send a help text."""
    chat_id, chat_type = get_chat_information(event.message.to_id)
    subscriber = Subscriber.get_or_create(session, chat_id, chat_type, chat_id)
    await event.respond(get_info_text(subscriber))


@archive.on(events.NewMessage(pattern='/set_name'))
@session_wrapper()
async def set_name(event, session):
    """Set query attributes."""
    chat_id, chat_type = get_chat_information(event.message.to_id)
    channel_name = event.message.message.split(' ', maxsplit=1)[1]
    subscriber = Subscriber.get_or_create(session, chat_id, chat_type, channel_name)

    old_channel_path = get_channel_path(subscriber.channel_name)
    new_channel_path = get_channel_path(channel_name)

    new_real_path = os.path.realpath(new_channel_path)
    target_real_path = os.path.realpath(config.TARGET_DIR)
    if not new_real_path.startswith(target_real_path) or \
            new_real_path == target_real_path:
        text = "Please stop fooling around and trying to escape the directory."
        await event.respond(text)

        return

    if os.path.exists(new_channel_path):
        text = "Channel name already exists. Please choose another one."
        await event.respond(text)

    elif old_channel_path != new_channel_path:
        subscriber.channel_name = channel_name
        if os.path.exists(old_channel_path):
            os.rename(old_channel_path, new_channel_path)
        text = "Channel name changed."
        await event.respond(text)

    session.commit()


@archive.on(events.NewMessage(pattern='/verbose'))
@session_wrapper()
async def set_verbose(event, session):
    """Set query attributes."""
    chat_id, chat_type = get_chat_information(event.message.to_id)
    subscriber = Subscriber.get_or_create(session, chat_id, chat_type, chat_id)

    # Convert the incoming text into an boolean
    try:
        value = get_bool_from_text(event.message.message.split(' ', maxsplit=1)[1])
    except Exception:
        text = "Got an invalid value. Please use one of [true, false, on, off, 0, 1]"
        return await event.respond(text)

    subscriber.verbose = value
    text = f"I'm now configured to be {'verbose' if value else 'sneaky'}."
    await event.respond(text)

    session.commit()


@archive.on(events.NewMessage(pattern='/sort_by_user'))
@session_wrapper()
async def set_sort_by_user(event, session):
    """Set query attributes."""
    chat_id, chat_type = get_chat_information(event.message.to_id)
    subscriber = Subscriber.get_or_create(session, chat_id, chat_type, chat_id)

    # Convert the incoming text into an boolean
    try:
        value = get_bool_from_text(event.message.message.split(' ', maxsplit=1)[1])
    except Exception:
        text = "Got an invalid value. Please use one of [true, false, on, off, 0, 1]"
        return await event.respond(text)

    subscriber.sort_by_user = value
    text = f"{'Sorting' if value else 'Not sorting'} by user."
    await event.respond(text)

    session.commit()


@archive.on(events.NewMessage(pattern='/accept'))
@session_wrapper()
async def accepted_media_types(event, session):
    """Set query attributes."""
    chat_id, chat_type = get_chat_information(event.message.to_id)
    subscriber = Subscriber.get_or_create(session, chat_id, chat_type, chat_id)

    # Convert the incoming text into an boolean
    arguments = event.message.message.lower().split(' ')[1:]
    accepted_media = set()
    for argument in arguments:
        if argument in possible_media:
            accepted_media.add(argument)

    accepted_media = list(accepted_media)
    accepted_media.sort()

    subscriber.accepted_media = ' '.join(accepted_media)
    text = f"Now accepting following media types: {accepted_media}."
    await event.respond(text)

    session.commit()


@archive.on(events.NewMessage(pattern='/start'))
@session_wrapper()
async def start(event, session):
    """Start the bot."""
    chat_id, chat_type = get_chat_information(event.message.to_id)

    subscriber = Subscriber.get_or_create(session, chat_id, chat_type, chat_id)
    subscriber.active = True
    session.add(subscriber)
    session.commit()

    text = 'Files posted in this channel will now be archived.'
    await event.respond(text)


@archive.on(events.NewMessage(pattern='/stop'))
@session_wrapper()
async def stop(event, session):
    """Stop the bot."""
    chat_id, chat_type = get_chat_information(event.message.to_id)

    subscriber = Subscriber.get_or_create(session, chat_id, chat_type, chat_id)
    subscriber.active = False
    session.add(subscriber)
    session.commit()

    text = "Files won't be archived any longer."
    await event.respond(text)


@archive.on(events.NewMessage())
@session_wrapper(addressed=False)
async def process(event, session):
    """Check if we received any files."""
    message = event.message
    chat_id, chat_type = get_chat_information(event.message.to_id)
    subscriber = Subscriber.get_or_create(session, chat_id, chat_type, chat_id)

    # If this message is forwarded, get the original sender.
    if message.forward:
        user = await message.forward.get_sender()
    else:
        user = await archive.get_entity(message.from_id)

    # Check if we should accept this message
    if not should_accept_message(subscriber, message, user):
        return

    # Get file type and id
    file_type, file_id = await get_file_information(event, message, subscriber, user)
    if not file_type:
        return

    # Get and create paths for this file
    file_path, file_name = get_file_path(subscriber, get_username(user), message)

    # Check if this file already exists in the file system
    if await check_if_file_exists(event, file_path, file_name, subscriber, user):
        return

    # Create new file
    new_file = File(file_id, chat_id, message.id,
                    user.id, file_name, file_type)
    session.add(new_file)
    session.commit()

    # Download the file
    if file_path:
        success = await message.download_media(file_path)
    else:
        success = await message.download_media()

    # Download succeeded, if the result is not None
    if success is not None:
        # Mark the file as succeeded
        new_file.success = True
    session.commit()


async def get_file_information(event, message, subscriber, user):
    """Check whether we got an allowed file type."""
    file_id = None
    file_type = None

    accepted_media = subscriber.accepted_media.split(' ')

    if 'photo' in accepted_media \
            and message.photo is not None:
        file_type = 'photo'
        file_id = message.photo.id
    elif message.photo is not None:
        # Flame the user that compressed photos are evil
        if subscriber.verbose:
            text = f"Please send uncompressed files @{user.username} :(."
            await event.respond(text)

    if 'document' in accepted_media \
            and message.document is not None:
        file_type = 'document'
        file_id = message.document.id

    return file_type, file_id


archive.start(bot_token=config.TELEGRAM_BOT_API_KEY)
