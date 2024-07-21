import asyncio
from typing import Optional, Union

import disnake
from disnake.abc import Connectable

from botbase import BotBase

from mafic import Player, Track
from random import randint
from typing import Optional
from utils.converter import trim_text, time_format
from collections import deque

MessageableChannel = Union[disnake.TextChannel, disnake.Thread, disnake.VoiceChannel, disnake.StageChannel, disnake.PartialMessageable]


SOURCE_LOGO = {
	"youtube": "https://static.vecteezy.com/system/resources/previews/018/930/572/original/youtube-logo-youtube-icon-transparent-free-png.png",
	"spotify": "https://i.pinimg.com/474x/30/6f/6a/306f6a14403921a4d8b4ab53d3c9f2a3.jpg",
	"soundcloud": "https://img.freepik.com/premium-vector/soundcloud-logo_578229-231.jpg",
}
SOURCE_LOGO_DEFAULT = "https://cdn.discordapp.com/emojis/884721193381412884.gif?quality=lossless"

class LoopMode(enumerate):
	OFF = 0
	SONG = 1
	PLAYLIST = 2


class Queue:
	def __init__(self):
		self.current_track: Track = None

		self.played: deque[Track] = deque()
		self.upcoming: deque[Track] = deque()

		self.loop = LoopMode.OFF
		self.shuffle: bool = False

	def get_upcoming(self):
		return [track for track in self.upcoming]

	def _continue(self) -> Optional[Track]:
		if self.loop == LoopMode.SONG:
			return self.current_track
		else:
			return self.next()

	def previous(self) -> Optional[Track]:
		if self.played.__len__() == 0:
			return None

		if self.current_track is not None:
			self.upcoming.appendleft(self.current_track)
		self.current_track = self.played.pop()
		return self.current_track


	def next(self):
		if self.upcoming.__len__() == 0 and self.loop == LoopMode.PLAYLIST:
			for track in self.played:
				self.upcoming.append(track)
			self.played.clear()

		if self.current_track is not None:
			self.played.append(self.current_track)
			self.current_track = None

		if self.upcoming.__len__() != 0:
			if self.shuffle:
				index = randint(0, self.upcoming.__len__() - 1)
				self.current_track = self.upcoming[index]
				del self.upcoming[index]
			else:
				self.current_track = self.upcoming.popleft()

		return self.current_track

	def add(self, track: Track):
		self.upcoming.append(track)

	def clear(self):
		self.upcoming.clear()
		self.played.clear()




class VoiceSessionHandler(Player[BotBase]):
	def __init__(self, bot: BotBase, channel: Connectable) -> None:
		super().__init__(bot, channel)
		self.bot = bot
		self.channel = channel
		self.queue: Queue = Queue()
		self.notification_channel: MessageableChannel = None
		self.message_hook: list = None

		self.__update_controller_lock__ = asyncio.Lock()
		
		
	async def __send_notification__(self, **kwargs):
		try:
			await self.notification_channel.send(**kwargs)
		except:
			self.notification_channel = None


	async def update_controller(self):
		async with self.__update_controller_lock__:
			replace = int(disnake.utils.utcnow().timestamp()) - self.message_hook[2] < 300
			if self.message_hook is not None and not replace:
				try:
					await self.bot.http.delete_message(self.message_hook[0], self.message_hook[1])
				finally:
					self.message_hook = None
			if self.notification_channel is not None:
				try:
					if replace and self.message_hook is not None:
						await self.bot.http.edit_message(
							channel_id=self.message_hook[0],
							message_id=self.message_hook[1],
							**render_controller(self)
						)
						self.message_hook[2] = int(disnake.utils.utcnow().timestamp())
					else:
						msg = await self.notification_channel.send(**render_controller(self))
						self.message_hook = [self.notification_channel.id, msg.id, int(disnake.utils.utcnow().timestamp())]
				except:
					self.message_hook = None
					self.notification_channel = None


	async def next(self):
		track = self.queue._continue()
		if track is None:
			if self.notification_channel is not None:
				await self.__send_notification__(embed=EMPTY_QUEUE)
			await self.disconnect(force=True)
			return
		await self.play(track, replace=True)
		await self.update_controller()

	async def previous(self) -> bool:
		track = self.queue.previous()
		if track is None:
			return False
		await self.play(track, replace=True)
		await self.update_controller()
		return True

	async def _continue(self):
		track = self.queue._continue()
		if track is None:
			if self.notification_channel is not None:
				await self.__send_notification__(embed=EMPTY_QUEUE)
			await self.disconnect(force=True)
			return
		await self.play(track, replace=True)
		await self.update_controller()

EMPTY_QUEUE = disnake.Embed(
	title="👋 Danh sách chờ đã hết. Bot sẽ rời khỏi kênh của bạn",
	color=0xFFFFFF
)

TRACK_LOAD_FAILED = disnake.Embed(
	title="❌ Đã có lỗi xảy ra khi tìm kiếm bài hát được yêu cầu",
	color=0xFF0000
)


def render_controller(player: VoiceSessionHandler) -> dict:
	track = player.queue.current_track
	embed = disnake.Embed(
		title=trim_text(track.title, 32),
		url=track.uri,
		color=0xFFFFFF
	)
	embed.set_author(
		name="Đang tạm dừng" if player.paused else f"Đang phát từ {track.source.capitalize()}",
		icon_url=SOURCE_LOGO.get(track.source, SOURCE_LOGO_DEFAULT)
	)
	embed.set_thumbnail(track.artwork_url)

	embed.add_field(name="👤 Tác giả", value=f"> `{track.author}`", inline=True)

	embed.add_field(
		name=("🔴" if track.stream else "🕒") + " Thời lượng",
		value="> `Trực tiếp`" if track.stream else f"> `{time_format(track.length)}`",
		inline=True
	)

	upcoming = player.queue.upcoming.__len__()
	if upcoming != 0:
		embed.add_field(name="📝 Hàng đợi", value=f"> `{upcoming} bài hát`", inline=True)

	if player.queue.loop == LoopMode.PLAYLIST:
		embed.add_field(name="🔁 Lặp lại", value="> `Danh sách phát`", inline=True)
	elif player.queue.loop == LoopMode.SONG:
		embed.add_field(name="🔂 Lặp lại", value="> `Bài hát hiện tại`", inline=True)

	if player.queue.shuffle:
		embed.add_field(name="🔀 Trộn bài", value="> `Bật`", inline=True)

	embed.set_footer(
		text=f"Máy chủ Lavalink: {player.node.label}",
		icon_url="https://avatars.githubusercontent.com/u/133400169?v=4"
	)

	view = disnake.ui.View(timeout=(track.length // 1000) if not player.paused else None)
	view.add_item(disnake.ui.Button(emoji="⏮️", custom_id="music_previous", row=1))
	view.add_item(disnake.ui.Button(
		style=disnake.ButtonStyle.primary if player.paused else disnake.ButtonStyle.secondary,
		emoji="▶️" if player.paused else "⏸️",
		custom_id="music_pause",
		row=1
	))
	view.add_item(disnake.ui.Button(emoji="⏭️", custom_id="music_next", row=1))
	view.add_item(disnake.ui.Button(emoji="⏹️", custom_id="music_stop", row=1))

	return {"embed": embed, "view": view}


class QueueInterface(disnake.ui.View):

	def __init__(self, player: VoiceSessionHandler, timeout = 60):
		self.player = player
		self.pages = []
		self.selected = []
		self.current = 0
		self.max_pages = len(self.pages) - 1
		self.message: Optional[disnake.Message] = None
		super().__init__(timeout=timeout)
		self.embed = disnake.Embed()
		self.update_pages()
		self.update_embed()

	def update_pages(self):

		counter = 1

		self.pages = list(disnake.utils.as_chunks(self.player.queue.upcoming, max_size=12))
		self.selected.clear()

		self.clear_items()

		for n, page in enumerate(self.pages):

			txt = "\n"
			opts = []

			for t in page:
				duration = time_format(t.length) if not t.stream else '🔴 Livestream'

				txt += f"`┌ {counter})` [`{trim_text(t.title, limit=50)}`]({t.uri})\n" \
					   f"`└ ⏲️ {duration}`"

				opts.append(
					disnake.SelectOption(
						label=f"{counter}. {t.author}"[:25], description=f"[{duration}] | {t.title}"[:50],
						value=f"queue_select_{t.id}",
					)
				)

				counter += 1

			self.pages[n] = txt
			self.selected.append(opts)

		first = disnake.ui.Button(emoji='⏮️', style=disnake.ButtonStyle.grey)
		first.callback = self.first
		self.add_item(first)

		back = disnake.ui.Button(emoji='⬅️', style=disnake.ButtonStyle.grey)
		back.callback = self.back
		self.add_item(back)

		next = disnake.ui.Button(emoji='➡️', style=disnake.ButtonStyle.grey)
		next.callback = self.next
		self.add_item(next)

		last = disnake.ui.Button(emoji='⏭️', style=disnake.ButtonStyle.grey)
		last.callback = self.last
		self.add_item(last)

		stop_interaction = disnake.ui.Button(emoji='⏹️', style=disnake.ButtonStyle.grey)
		stop_interaction.callback = self.stop_interaction
		self.add_item(stop_interaction)

		update_q = disnake.ui.Button(emoji='🔄', label="Làm mới", style=disnake.ButtonStyle.grey)
		update_q.callback = self.update_q
		self.add_item(update_q)

		self.current = 0
		self.max_page = len(self.pages) - 1

	async def on_timeout(self) -> None:

		if not self.message:
			return

		embed = self.message.embeds[0]
		embed.set_footer(text="Đã hết thời gian tương tác!")

		for c in self.children:
			c.disabled = True

		await self.message.edit(embed=embed, view=self)

	def update_embed(self):
		self.embed.title = f"**Trang [{self.current + 1} / {self.max_page + 1}]**"
		self.embed.description = self.pages[self.current]
		self.children[0].options = self.selected[self.current]

		for n, c in enumerate(self.children):
			if isinstance(c, disnake.ui.StringSelect):
				self.children[n].options = self.selected[self.current]

	async def first(self, interaction: disnake.MessageInteraction):

		self.current = 0
		self.update_embed()
		await interaction.response.edit_message(embed=self.embed, view=self)

	async def back(self, interaction: disnake.MessageInteraction):

		if self.current == 0:
			self.current = self.max_page
		else:
			self.current -= 1
		self.update_embed()
		await interaction.response.edit_message(embed=self.embed, view=self)

	async def next(self, interaction: disnake.MessageInteraction):

		if self.current == self.max_page:
			self.current = 0
		else:
			self.current += 1
		self.update_embed()
		await interaction.response.edit_message(embed=self.embed, view=self)

	async def last(self, interaction: disnake.MessageInteraction):

		self.current = self.max_page
		self.update_embed()
		await interaction.response.edit_message(embed=self.embed, view=self)

	async def stop_interaction(self, interaction: disnake.MessageInteraction):

		await interaction.response.edit_message(content="Đóng", embed=None, view=None)
		self.stop()

	async def update_q(self, interaction: disnake.MessageInteraction):

		self.current = 0
		self.max_page = len(self.pages) - 1
		self.update_pages()
		self.update_embed()
		await interaction.response.edit_message(embed=self.embed, view=self)
