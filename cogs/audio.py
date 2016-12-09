import discord
from discord.ext import commands
from cogs.utils.helpers import *
from cogs.utils.clip import *
from __main__ import settings, botdata
from cogs.utils import checks
import asyncio
import os
import string
import queue
import random
from .mangocog import *
from ctypes.util import find_library

discord.opus.load_opus(find_library('opus'))

def get_clipdirs():
	result = []
	for root, dirs, files in os.walk(settings.resourcedir + "clips/"):
		for d in dirs:
			result.append(d)
	result.sort()
	return result

# gets a list of all the mp3s in the indicated clipdir
def get_playlist(clipdir):
	clips = []
	for root, dirs, files in os.walk(settings.resourcedir + "clips/" + clipdir):
		for file in files:
			if file.endswith(".mp3"):
				clips.append(file[:-4])
	clips.sort()
	return clips

def remove_if_temp(mp3name):
	if os.path.isfile(mp3name):
		if os.path.dirname(mp3name) == os.path.join(settings.resourcedir, "temp"):
			os.remove(mp3name)
			print("removed temp file " + mp3name)

class Audio(MangoCog):
	"""Commands used to play audio
	"""

	def __init__(self, bot):
		MangoCog.__init__(self, bot)
		self.voice = None
		self.player = None
		self.clipqueue = queue.Queue()
		self.last_clip = None


	# whether or not the bot is currently talking
	def is_talking(self):
		return (self.player is not None) and (not self.player.is_done())

	def done_talking(self):
		self.player = None
		if not self.clipqueue.empty():
			self.play_next_clip()

	# gets the next clip from the clip queue
	def next_clip(self):
		if not self.clipqueue.empty():
			return self.clipqueue.get()
		raise ValueError("clip queue was empty when we tried to get the next one")

	# plays the next clip in the queue
	def play_next_clip(self):
		try:
			clip = self.next_clip()
			self.player = self.voice.create_ffmpeg_player(clip.audiopath, after=self.done_talking)
			self.player.volume = clip.volume
			self.player.start()
			print("playing: " + clip.audiopath)
			if self.last_clip != None and clip.audiopath != self.last_clip.audiopath:
				remove_if_temp(self.last_clip.audiopath)
			self.last_clip = clip
		except Exception as e:
			print(str(e))

	# try queueing an mp3 to play
	async def queue_clip(self, clip):
		if(self.voice is None):
			print("tried to talk while not in voice channel")
			await self.bot.say("not in voice channel m8")
			return

		self.clipqueue.put(clip)

		if not self.is_talking():
			self.play_next_clip()

	@commands.command(pass_context=True)
	async def play(self, ctx, clip : str=""):
		"""Plays an audio clip

		example:
		?play hello

		for a complete list of the available clips, try ?playlist"""
		try:
			await self.play_clip("local:" + clip)
		except ClipNotFound:
			await self.bot.say("'" + clip + "' is not a valid clip. 🤦 Try ?playlist. ")
			

	@commands.command(pass_context=True)
	async def playlist(self, ctx, section : str=""):
		"""Lists the audio clips available for ?play

		Calling this command with no arguments gets you a list of sections

		To get the clips in a specific section, do ?playlist <section>"""
		dirs = get_clipdirs()

		message = ""

		if ((not section in dirs) and section != ""):
			message +=("Thats not a valid section...\n")
			section = ""

		clips = get_playlist(section)
		if section == "":
			message += "Pick a section and do ?playlist <section>\n"
			message += "Sections:\n"
			for d in dirs:
				message += " - " + d + "\n"
		else:
			message += "```\n"
			for clip in clips:
				message += clip + "\n"
			message += "```"
		await self.bot.say(message)

	@commands.command(pass_context=True)
	async def playurl(self, ctx, mp3url : str):
		"""Plays an mp3 file at a url

		Make sure to use http, not https"""
		await self.play_clip("url:" + mp3url)

	@commands.command(pass_context=True)
	async def stop(self, ctx):
		"""Stops the currently playing audio

		Also empties the clip queue
		"""
		while not self.clipqueue.empty():
			try:
				self.clipqueue.get()
			except Empty:
				continue
		if not self.player is None:
			self.player.stop();

	@commands.command(pass_context=True)
	async def replay(self, ctx):
		"""Replays the last played clip
		"""
		if self.last_clip == None:
			await self.bot.say("Nobody said anythin' yet")
			return

		# If its not a temp file
		await self.bot.say("Replaying " + self.last_clip.clipid)

		await self.queue_clip(self.last_clip)

	@commands.command(pass_context=True)
	async def clipinfo(self, ctx, clipid=None):
		"""Gets info about the indicated clip

		no clipid will print info about the last clip played

		clipid is specified like this:
		local:shitpickle
		dota:timb_ally_01
		"""
		if clipid is None:
			if self.last_clip == None:
				await self.bot.say("Nobody said anythin' yet")
				return
			clipid = self.last_clip.clipid

		clip = await self.get_clip(clipid)

		await self.bot.say(embed=await clip.get_info_embed(self.bot))


	@commands.command(pass_context=True)
	async def setintro(self, ctx, clipname : str, user: discord.User=None):
		"""Sets your intro clip

		The argument is the name of the clip that will introduce you, for example:
		?setintro math
		Note: your intro clip cannot be longer than 4 seconds
		"""
		if user is None:
			user = ctx.message.author
		else:
			if not await checks.is_owner_check(ctx):
				await self.bot.say("You aint the boss of me 😠")
				return

		try:
			clip = await self.get_clip(clipname)
		except MissingClipType:
			clip = await self.get_clip("local:" + clipname)

		audiolength = clip.audiolength

		if audiolength > 4.0:
			await self.bot.say("Dat clip is " + str(audiolength) + " seconds long, and intros gotta be less than 3.")
			return

		botdata.userinfo(user.id).intro = clip.clipid

		await self.bot.say("Yer intro is now " + clip.clipid)

	@commands.command(pass_context=True)
	async def tts(self, ctx, *, message : str):
		"""Like ?echo but for people who can't read

		...what more could you possibly need to know...
		"""
		await self.play_clip("tts:" + message)

	#function called when this event occurs
	async def on_voice_state_update(self, before, after):
		if self.voice is None or after.voice_channel is None or before.voice_channel == after.voice_channel or before.voice_channel == after.voice_channel:
			# if the bot or the member are not in a voice channel, or if the member's channel didnt change, don't worry about checking that theyre equal
			return
		if after.voice_channel.id == self.voice.channel.id:
			print(after.name + " joined the channel")

			text = after.name
			introclip = "local:helloits"

			userinfo = botdata.userinfo(after.id)
			if userinfo.intro != "" and userinfo.intro != introclip:
				introclip = userinfo.intro
				text = "its " + after.name

			await asyncio.sleep(3)
			await self.play_clip(introclip)
			await self.play_clip("tts:" + text)


def setup(bot):
	bot.add_cog(Audio(bot))