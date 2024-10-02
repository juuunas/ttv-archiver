#!/usr/bin/env python
import asyncio
import streamlink
import os
from datetime import datetime
import re
import ffmpeg
import aiofiles
import requests
from websockets import connect

streamer = "juunnnnnnnnnnnnnas"
chat_messages = []
live = False

initCommands = [
    "CAP REQ :twitch.tv/tags twitch.tv/commands",
    "PASS SCHMOOPIIE",
    "NICK justinfan49345",
    "USER justinfan49345 8 * justinfan49345",
    "JOIN #" + streamer,
]


def getBestStream(channel):
    return streamlink.streams("https://twitch.tv/" + channel).get("best") or None


def getStreamerTitle(channel):
    return requests.post(
        "https://gql.twitch.tv/gql#origin=twilight",
        headers={
            "Client-Id": "kimne78kx3ncx6brgo4mv6wki5h1ko",
        },
        json=[
            {
                "operationName": "UseLiveBroadcast",
                "variables": {"channelLogin": channel},
                "extensions": {
                    "persistedQuery": {
                        "version": 1,
                        "sha256Hash": "0b47cc6d8c182acd2e78b81c8ba5414a5a38057f2089b1bbcfa6046aae248bd2",
                    }
                },
            }
        ],
    ).json()[0]["data"]["user"]["lastBroadcast"]["title"]


def isStreamerLive(channel):
    return (
        requests.post(
            "https://gql.twitch.tv/gql#origin=twilight",
            headers={
                "Client-Id": "kimne78kx3ncx6brgo4mv6wki5h1ko",
            },
            json=[
                {
                    "operationName": "UseLive",
                    "variables": {"channelLogin": channel},
                    "extensions": {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": "639d5f11bfb8bf3053b424d9ef650d04c4ebb7d94711d644afb08fe9a0fad5d9",
                        }
                    },
                },
            ],
        ).json()[0]["data"]["user"]["stream"]
        is not None
    )


def parse_irc_message(message):
    pattern = (
        r"^(?P<tags>@[^ ]+) (?P<prefix>:[^ ]+) (?P<command>\w+)( (?P<params>.*))?$"
    )
    match = re.match(pattern, message)

    if not match:
        print(f"Failed to parse message: {message}")
        return None

    tags = match.group("tags")[1:].split(";") if match.group("tags") else []
    tag_dict = {
        key_value.split("=", 1)[0]: key_value.split("=", 1)[1] for key_value in tags
    }

    prefix = match.group("prefix")[1:] if match.group("prefix") else None
    command = match.group("command")
    params = match.group("params").split(" ", 1) if match.group("params") else []

    if len(params) > 1:
        params[1] = params[1][1:]

    return {
        "tags": tag_dict,
        "prefix": prefix,
        "command": command,
        "params": params,
    }


async def joinChat():
    print("[IRC] Joining channel " + streamer)

    websocket = await connect("ws://irc-ws.chat.twitch.tv")
    try:
        for command in initCommands:
            await websocket.send(command)

        print("[IRC] Started parsing messages")

        async def listen():
            while True:
                try:
                    message = await websocket.recv()

                    if message.startswith("PING"):
                        await websocket.send("PONG")

                    parsedMessage = parse_irc_message(message)
                    if parsedMessage is not None:
                        if parsedMessage["command"] == "PRIVMSG":
                            user = parsedMessage["tags"]["display-name"]
                            chat_message = parsedMessage["params"][1].replace("\r", "")[
                                :75
                            ]
                            if len(chat_messages) + 1 > 20:
                                chat_messages.pop(0)
                            chat_messages.append(f"{user}: {chat_message}")

                except asyncio.CancelledError:
                    break

        task = asyncio.create_task(listen())
        try:
            while live:
                await asyncio.sleep(1)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    finally:
        if websocket.open:
            await websocket.close()

    print("[IRC] Offline")
    return None


async def updateMessages():
    print("[msg] Updating messages with new ones from IRC")
    dir_name = os.path.dirname("text.txt")
    while live:
        print("[msg] Updating messages...")

        async with aiofiles.tempfile.NamedTemporaryFile(
            "w", delete=False, dir=dir_name, suffix=".tmp", encoding="utf-8"
        ) as tmp_file:
            temp_file_path = tmp_file.name

            content = "\n".join(chat_messages)
            await tmp_file.write(content)

        if temp_file_path:
            try:
                os.replace(temp_file_path, "text.txt")
            except PermissionError as e:
                print(f"[msg] PermissionError occurred: {e}")
            finally:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
        print("[msg] Updated messages")

        await asyncio.sleep(0.5)

    print("[msg] Stopped")
    return None


def startRecordingStream(stream):
    filename = (
        f"{streamer} {getStreamerTitle(streamer)} {datetime.now().isoformat()}.mp4"
    )
    print("[VOD] Constructed filename: " + filename)
    input = ffmpeg.input(stream.url)
    ffmpeg_output = ffmpeg.output(
        input,
        filename,
        vf="drawtext=textfile=text.txt:reload=1:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.7:boxw=500:boxh=500:fix_bounds=true:",
        f="mp4",
    )

    try:
        ffmpeg_output.run()
        globals()["live"] = False
    except ffmpeg.Error:
        print("[VOD] Recording failed due to ffmpeg crash")
        return None

    print("[VOD] Saved recording to " + filename)
    return filename


async def main():
    print("Archiving streams from streamer " + streamer)
    while True:
        if isStreamerLive(streamer):
            stream = getBestStream(streamer)
            if stream:
                print("Streamer is live! Starting recording...")
                globals()["live"] = True
                _, _, filename = await asyncio.gather(
                    joinChat(),
                    updateMessages(),
                    asyncio.to_thread(startRecordingStream, stream),
                )

                globals()["chat_messages"] = []

                print("Uploading recording " + filename)
                # TODO upload recorded file
            else:
                print("Twitch API shows stream is live but playlist is unavailable!")
        else:
            print("Streamer is not live.")

        await asyncio.sleep(3.5)


if __name__ == "__main__":
    asyncio.run(main())
