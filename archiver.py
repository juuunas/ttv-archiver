#!/usr/bin/env python
import asyncio
import subprocess
import os
from datetime import datetime
import re
import ffmpeg
import aiofiles
import m3u8
import requests
from websockets import connect

streamer = os.environ.get("streamer", "juunnnnnnnnnnnnnas")
playlist_URI = f"https://lb-eu5.cdn-perfprod.com/playlist/{streamer}.m3u8%3Fallow_source%3Dtrue%26fast_bread%3Dtrue"
chat_messages = []
live = False
messagesOnScreen = 7
FAILED_UPLOADS_FILE = "failed_uploads.txt"

initCommands = [
    "CAP REQ :twitch.tv/tags twitch.tv/commands",
    "PASS SCHMOOPIIE",
    "NICK justinfan49345",
    "USER justinfan49345 8 * justinfan49345",
    "JOIN #" + streamer,
]


def getPlaylists():
    return requests.get(playlist_URI)


def getStreamerTitle(channel):
    try:
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
    except Exception as e:
        print("Failed to get title: " + repr(e))
        return None


def isStreamerLive(channel):
    try:
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
    except Exception as e:
        print("Failed to call UseLive: " + repr(e))
        return False


def parse_irc_messages(messages):
    pattern = (
        r"^(?P<tags>@[^ ]+) (?P<prefix>:[^ ]+) (?P<command>\w+)( (?P<params>.*))?$"
    )
    message_list = messages.strip().split("\r\n")
    parsed_messages = []

    for message in message_list:
        match = re.match(pattern, message)

        if not match:
            print(f"[IRC] Failed to parse message: {message}")
            continue

        tags = match.group("tags")[1:].split(";") if match.group("tags") else []
        tag_dict = {
            key_value.split("=", 1)[0]: key_value.split("=", 1)[1] for key_value in tags
        }

        prefix = match.group("prefix")[1:] if match.group("prefix") else None
        command = match.group("command")
        params = match.group("params").split(" ", 1) if match.group("params") else []

        if len(params) > 1:
            params[1] = params[1][1:]

        parsed_messages.append(
            {
                "tags": tag_dict,
                "prefix": prefix,
                "command": command,
                "params": params,
            }
        )

    return parsed_messages


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

                    parsedMessages = parse_irc_messages(message)
                    if parsedMessages is not None:
                        for msg in parsedMessages:
                            if msg["command"] == "PRIVMSG":
                                user = msg["tags"]["display-name"]
                                chat_message = msg["params"][1].replace("\r", "")[:75]
                                if len(chat_messages) + 1 > messagesOnScreen:
                                    chat_messages.pop(0)

                                truncated_message = f"{user}: {chat_message}"[:225]
                                formatted_message = ""
                                while len(truncated_message) > 50:
                                    split_index = truncated_message[:50].rfind(" ")
                                    if split_index == -1:
                                        split_index = 50
                                    formatted_message += (
                                        truncated_message[: split_index + 1] + "\n"
                                    )
                                    truncated_message = truncated_message[
                                        split_index + 1 :
                                    ]

                                formatted_message += truncated_message

                                chat_messages.append(formatted_message)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print("[IRC] Unknown error on WebSocket: " + e)

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
    print("[msg] Updating text.txt file with chat msgs from " + streamer)
    dir_name = os.path.dirname("text.txt")
    while live:
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

        await asyncio.sleep(0.2)

    print("[msg] Stopped")
    return None


def save_failed_upload(segment_filename, segment_index, total_segments):
    if not os.path.exists(FAILED_UPLOADS_FILE):
        with open(FAILED_UPLOADS_FILE, "w") as f:
            f.write("")

    with open(FAILED_UPLOADS_FILE, "r") as f:
        failed_files = {line.strip() for line in f.readlines()}

    entry = f"{segment_filename},{segment_index},{total_segments}"
    if entry not in failed_files:
        with open(FAILED_UPLOADS_FILE, "a") as f:
            f.write(entry + "\n")


def remove_successful_upload(filename):
    if not os.path.exists(FAILED_UPLOADS_FILE):
        return

    with open(FAILED_UPLOADS_FILE, "r") as f:
        lines = f.readlines()
    with open(FAILED_UPLOADS_FILE, "w") as f:
        for line in lines:
            if line.strip() != filename:
                f.write(line)


async def retry_failed_uploads():
    while True:
        if os.path.exists(FAILED_UPLOADS_FILE):
            with open(FAILED_UPLOADS_FILE, "r") as f:
                failed_entries = [
                    line.strip() for line in f.readlines() if line.strip()
                ]

            for entry in failed_entries:
                try:
                    segment_filename, segment_index, total_segments = entry.split(",")
                    segment_index = int(segment_index)
                    total_segments = int(total_segments)

                    title = (
                        f"[{segment_index}/{total_segments}] {os.path.splitext(segment_filename)[0]}"
                        if total_segments > 1
                        else os.path.splitext(segment_filename)[0]
                    )

                    print(f"[Uploader] Retrying upload for {title}...")
                    result = subprocess.run(
                        [
                            ".venv/bin/youtube-up",
                            "video",
                            segment_filename,
                            f"--title={title}",
                            f"--description={segment_filename}",
                            "--cookies_file=cookies/cookies.txt",
                            f"--privacy={os.environ.get('yt_privacy', 'PRIVATE')}",
                        ],
                    )
                    if result.returncode == 0:
                        print(f"[Uploader] Successfully uploaded {segment_filename}")
                        try:
                            os.remove(segment_filename)
                            remove_successful_upload(entry)
                        except Exception as e:
                            print(f"[Uploader] Error while cleaning up: {e}")
                            return None
                    else:
                        print(
                            f"[Uploader] Failed to upload {segment_filename}. Retrying later..."
                        )
                except Exception as e:
                    print(f"[Uploader] Error while retrying upload for {entry}: {e}")

        await asyncio.sleep(60)


async def upload(filename):
    print(f"[Uploader] Processing file {filename}...")

    clean_base_file = True
    segment_filenames = []
    try:
        base_name = os.path.splitext(filename)[0]
        probe = ffmpeg.probe(filename)
        duration = float(probe["format"]["duration"])
        total_hours = duration / 3600

        if total_hours > 10:
            segment_duration = 10 * 3600

            for i in range(0, int(duration), segment_duration):
                start_time = i
                end_time = min(start_time + segment_duration, duration)

                segment_filename = (
                    f"{base_name}_part_{i // segment_duration + 1:03d}.mp4"
                )
                segment_filenames.append(segment_filename)

                ffmpeg.input(
                    filename,
                    ss=start_time,
                    t=end_time - start_time,
                    loglevel="warning",
                ).output(segment_filename, c="copy").run()

        else:
            segment_filenames = [filename]

        for index, segment_filename in enumerate(segment_filenames):
            title = (
                f"[{index + 1}/{len(segment_filenames)}] {base_name} "
                if len(segment_filenames) > 1
                else base_name
            )
            print(f"[Uploader] Uploading segment {title}...")
            result = subprocess.run(
                [
                    ".venv/bin/youtube-up",
                    "video",
                    segment_filename,
                    f"--title={title}",
                    f"--description={filename}",
                    "--cookies_file=cookies/cookies.txt",
                    f"--privacy={os.environ.get("yt_privacy", "PRIVATE")}",
                ],
            )
            if result.returncode != 0:
                print(f"[Uploader] Upload failed for segment {segment_filename}")
                save_failed_upload(segment_filename, index + 1, len(segment_filenames))
                clean_base_file = False
    except Exception as e:
        print(f"[Uploader] Error occurred while segmenting and uploading: {e}")
        clean_base_file = False
        return None

    try:
        if len(segment_filenames) > 1:
            for name in segment_filename:
                os.remove(name)
        if clean_base_file:
            os.remove(filename)
    except Exception as e:
        print(f"[Uploader] Error while cleaning up: {e}")
        return None

    if not clean_base_file:
        return False

    print("[Uploader] All segments successfully uploaded and cleaned up!")
    return True


def startRecordingStream(playlists):
    filename = f"{streamer} {datetime.today().strftime('%Y-%m-%d %H:%M:%S')} {re.sub(r"\W+", " ", getStreamerTitle(streamer))[:60]}.mp4"

    print("[VOD] Constructed filename: " + filename)

    print("[VOD] Getting best stream")
    splaylist = None
    for playlist in m3u8.loads(playlists).playlists:
        resolution = playlist.stream_info.resolution
        if (
            resolution[0] <= 1280
            and resolution[1] <= 720
            and playlist.stream_info.frame_rate <= 30
        ):
            if not splaylist or (
                splaylist and splaylist.stream_info.resolution[0] < resolution[0]
            ):
                splaylist = playlist

    print(
        f"[VOD] Got best stream with resolution {splaylist.stream_info.resolution[0]}x{splaylist.stream_info.resolution[1]}"
    )

    input = ffmpeg.input(splaylist.uri)
    ffmpeg_output = ffmpeg.output(
        input,
        filename,
        vf="drawtext=textfile=text.txt:reload=1:fontcolor=white@0.9:fontsize=14:box=1:boxcolor=black@0.4:boxborderw=6:fontfile=Inter.ttf:fix_bounds=true:borderw=1:bordercolor=black@0.4:x=20:y=main_h-text_h-40:boxw=350:line_spacing=4:expansion=none",
        f="mp4",
        loglevel="warning",
    )

    try:
        print("[VOD] ffmpeg running...")
        ffmpeg_output.run()
        globals()["live"] = False
    except ffmpeg.Error:  # TODO Better error handling here
        print("[VOD] Recording failed due to ffmpeg crash")
        globals()["live"] = False
        return None

    print("[VOD] Saved recording to " + filename)
    return filename


async def main():
    print("Archiving streams from streamer " + streamer)

    asyncio.create_task(retry_failed_uploads())

    while True:
        if isStreamerLive(streamer):
            playlists = getPlaylists()
            if playlists.status_code == 200:
                print("Live. Starting...")
                globals()["live"] = True
                _, _, filename = await asyncio.gather(
                    joinChat(),
                    updateMessages(),
                    asyncio.to_thread(startRecordingStream, playlists.text),
                )

                globals()["chat_messages"] = []

                asyncio.create_task(upload(filename))
            else:
                print("Twitch API shows stream is live but playlist is unavailable!")

        await asyncio.sleep(3.5)


if __name__ == "__main__":
    asyncio.run(main())
