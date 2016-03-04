#!/usr/bin/env python3

"""
Listens to commands via HTTP for controlling a simple Christmas ornament.

 0 0 0 0 0   0 00001 111 11  111122222  22 2 2 23
 0 1 2 3 4   5 67890 123 45  678901234  56 7 8 90
 | | | | |   | ||||| ||| ||  |||||||||  || | | ||
04      06    13        21      30        42   43 - y=0
  03  05    12 14     20 22    2931     41        - y=1
    02      11  15   19  23   28  32        40    - y=2
  01  07    10   16 18   24  27 33 34  36      39 - y=3
00      08  09    17     25 26      35    37  38  - y=4
"""

from PIL import Image, ImageDraw
import colorsys
import http.server
import json
import mimetypes
import os
import queue
import random
import shutil
import socketserver
import sys
import threading
import time
import urllib.parse

try:
	import neopixel
except ImportError:
	neopixel = None

TIMEOUT = 0.04
GPIO_PIN = 18
BRIGHTNESS = 64

class Pixel(object):
	def __init__(self, chain_pos, x, y):
		self.chain_pos = chain_pos
		self.x = x
		self.y = y
		self.r = 0xFF
		self.g = 0
		self.b = 0

	def grb(self):
		return ((self.g << 16) | (self.r << 8) | (self.b << 0))

	def rgb(self):
		return ((self.r << 16) | (self.g << 8) | (self.b << 0))

	def triplet(self):
		return (self.r, self.g, self.b)

	def set(self, r, g, b):
		self.r = r
		self.g = g
		self.b = b

	def dim(self, amount):
		"""amount - 0..1 where zero means blank and 1 means no change."""
		self.r = int(self.r * amount)
		self.g = int(self.g * amount)
		self.b = int(self.b * amount)

	def __str__(self):
		return "Pixel({}, x={}, y={}, color={:02x}{:02x}{:02x})".format(
			self.chain_pos,
			self.x,
			self.y,
			self.r,
			self.g,
			self.b)

	def __repr__(self):
		return "Pixel({}, x,y=({}, {}), color={:02x}{:02x}{:02x})".format(
			self.chain_pos,
			self.x,
			self.y,
			self.r,
			self.g,
			self.b)

x = 0
PIXELS = [
	Pixel(n, x, y) for (n, (x, y)) in enumerate([
	# X
	(0,  4),
	(1,  3),
	(2,  2),
	(1,  1),
	(0,  0),
	(3,  1),
	(4,  0),
	(3,  3),
	(4,  4),
	# M
	(5,  4),
	(5,  3),
	(5,  2),
	(5,  1),
	(6,  0),
	(7,  1),
	(8,  2),
	(9,  3),
	(10, 4),
	(11, 3),
	(12, 2),
	(13, 1),
	(14, 0),
	(15, 2),
	(15, 1),
	(15, 3),
	(15, 4),
	# A
	(16, 4),
	(17, 3),
	(18, 2),
	(19, 1),
	(20, 0),
	(21, 1),
	(22, 2),
	(20, 3),
	(23, 3),
	(24, 4),
	# S
	(25, 3),
	(27, 4),
	(29, 4),
	(30, 3),
	(28, 2),
	(26, 1),
	(27, 0),
	(30, 0)
	])
]

ROWS = []
COLS = []
for p in PIXELS:
	while p.y >= len(ROWS):
		ROWS.append(list())
	ROWS[p.y].append(p)
	while p.x >= len(COLS):
		COLS.append(list())
	COLS[p.x].append(p)

MESSAGE_QUEUE = queue.Queue()

class BitmapOut:
	X_SPACE = 20
	Y_SPACE = 30
	X_HEIGHT = X_SPACE * 32
	Y_HEIGHT = Y_SPACE * 6
	RADIUS = 5

	def __init__(self, filename_root, single=True):
		print("Creating bitmap output, filename_root={0}".format(filename_root))
		self.idx = 0
		self.filename_root = filename_root
		self.single = single

	def render(self):
		"""Given a collection of pixels, produces a bitmap.
		"""
		im = Image.new("RGB", (self.X_HEIGHT, self.Y_HEIGHT), "grey")
		draw = ImageDraw.Draw(im)
		for p in PIXELS:
			x = (p.x + 1) * self.X_SPACE
			y = (p.y + 1) * self.Y_SPACE
			# print("Drawing {:06x} at ({},{})".format(p.rgb(), x, y))
			draw.ellipse((x - self.RADIUS, y - self.RADIUS, x + self.RADIUS, y + self.RADIUS), fill=p.triplet())
		if self.single:
			filename = "{root}.png".format(root=self.filename_root)
		else:
			filename = "{root}{idx:04d}.png".format(root=self.filename_root, idx=self.idx)
		im.save(filename)
		self.idx = self.idx + 1

	def setBrightness(self, brightness):
		pass

class PixelsOut:
	def __init__(self, gpio_pin):
		print("Creating pixel output, GPIO={0}".format(gpio_pin))
		self.gpio_pin = gpio_pin
		self.neo = neopixel.Adafruit_NeoPixel(len(PIXELS), gpio_pin, freq_hz=400000, invert=False)
		self.neo.begin()
		self.neo.setBrightness(BRIGHTNESS)

	def render(self):
		"""Gets the C library to bash the pixels
		out over DMA/PWM.
		"""
		for index, pixel in enumerate(PIXELS):
			r, g, b = pixel.triplet()
			self.neo.setPixelColorRGB(index, g, r, b)
		self.neo.show()

	def setBrightness(self, brightness):
		self.neo.setBrightness(min(brightness, 255))

def generate_colour(num, count, rotate):
	"""Create an RGB colour value from an HSV colour wheel.
	num - index from the rainbow
	count - number of items in the rainbow
	rotate - number between 0 and 1 to rotate the rainbow from its
		usual red first, violet last.
	"""
	h = num / count
	h = h + rotate
	# Fold back into 0..1
	h = h - int(h)
	s = 1
	v = 1
	r, g, b = colorsys.hsv_to_rgb(h, s, v)
	return (int(r * 255), int(g * 255), int(b * 255))

def static():
	"""The least interesting mode. All LEDs at the same colour and brightness.
	"""
	# @todo get colour from web UI
	for p in PIXELS:
		p.set(*static.colour)
	yield 1
static.colour = (0, 0xff, 0)

def walk():
	"""Illumatinate each LED in turn.
	"""
	for p in PIXELS:
		for p2 in PIXELS:
			p2.set(0, 0, 0)
		p.set(0xff, 0, 0)
		yield 0.5

def snowflakes(steps=100):
	"""All red, with falling white pixels representing snow.

	@todo make snow 2x2, as 1x1 doesn't show up well in most columns.
	"""
	def render_snow(cols, flakes, flake_chance):
		new_flakes = []
		# Move all existing flakes down, if they are not at the bottom
		for (x,y) in flakes:
			if (y+1) < len(cols):
				new_flakes.append((x, y + 1))

		# Make some new flakes
		if random.random() < flake_chance:
			col = random.randrange(0, len(cols))
			new_flakes.append((col, 0))

		# Map flakes to pixels
		for col in cols:
			for pixel in col:
				if (pixel.x, pixel.y) in new_flakes:
					pixel.set(0xff, 0xff, 0xff)
				else:
					pixel.set(0xff, 0, 0)
		return new_flakes

	flakes = []
	for i in range(0, steps):
		flakes = render_snow(COLS, flakes, 0.7)
		yield 0.1

def rainbow_cols(steps=100):
	"""Generate a rainbow pattern which rotates.
	"""
	for i in range(0, steps):
		for (idx, li) in enumerate(COLS):
			r,g,b = generate_colour(idx, len(COLS), 1-i/steps)
			for pixel in li:
				pixel.set(r, g, b)
		yield TIMEOUT

def rainbow_rows(steps=100):
	"""Generate a rainbow pattern which rotates.
	"""
	for i in range(0, steps):
		for (idx, li) in enumerate(ROWS):
			r,g,b = generate_colour(idx, len(ROWS), 1-i/steps)
			for pixel in li:
				pixel.set(r, g, b)
		yield TIMEOUT

def larsen():
	DIM_FACTOR = 0.9
	OVERSHOOT = 10
	for pixel in PIXELS:
		pixel.set(0, 0, 0)
	for i in range(0, len(COLS) + OVERSHOOT):
		for idx, li in enumerate(COLS):
			for pixel in li:
				if idx == i:
					pixel.set(0xff, 0, 0)
				else:
					pixel.dim(DIM_FACTOR)
		yield TIMEOUT
	for i in range(len(COLS)-1, -OVERSHOOT, -1):
		for idx, li in enumerate(COLS):
			for pixel in li:
				if idx == i:
					pixel.set(0xff, 0, 0)
				else:
					pixel.dim(DIM_FACTOR)
		yield TIMEOUT

class MyRequestHandler(http.server.BaseHTTPRequestHandler):

	def do_HEAD(self):
		self.do_REQ(True)

	def do_GET(self):
		self.do_REQ(False)

	def do_POST(self):
		content_len = int(self.headers.get('content-length', 0))
		post_body = self.rfile.read(content_len)
		post_data = urllib.parse.parse_qs(post_body)
		print("Got body: {body!r}".format(body=post_body))
		try:
			for (key, value) in post_data.items():
				print("Key {key!r} = {value!r}".format(key=key, value=value))
				value = value[0].decode("ascii")
				key = key.decode("ascii")
				if key == "mode":
					routine = {
						"rainbow_rows": rainbow_rows,
						"rainbow_cols": rainbow_cols,
						"larsen": larsen,
						"walk": walk,
						"static": static,
						"snowflakes": snowflakes
					}[value]
					MESSAGE_QUEUE.put(("routine", routine))
				elif key == "brightness":
					MESSAGE_QUEUE.put(("brightness", min(int(value), 255)))
				elif key == "colour" and value[0].startswith("#"):
					red = int(value[1:3], 16)
					green = int(value[3:5], 16)
					blue = int(value[5:7], 16)
					triplet = (red, green, blue)
					MESSAGE_QUEUE.put(("colour", triplet))
				else:
					raise ValueError("Didn't understand message")
			self.send_response(200)
			self.send_header("Content-type", "application/json")
			self.end_headers()
			self.writeutf8('{ "status": "OK" }');
		except Exception as e:
			self.send_error(500, "Server Error: {!r}".format(e))

	def do_REQ(self, head):
		if self.path == "/":
			self.do_index(head)
		elif self.path.startswith("/slides") and (".." not in self.path):
			self.do_slides(head)
		else:
			self.send_error(404, "Page not found")

	def writeutf8(self, string):
		self.wfile.write(string.encode("utf-8"))

	def do_slides(self, head):
		"""Serve up static files for the slide deck which describes this project.
		Looks for files rooted in  ./slides.
		"""
		file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), self.path[1:]))
		try:
			with open(file_path, "rb") as f:
				mime, encoding = mimetypes.guess_type(self.path)
				self.send_response(200)
				self.send_header("Content-type", mime)
				self.end_headers()
				if not head:
					self.log_message("Sending file {file} as {mime}".format(file=file_path, mime=mime))
					shutil.copyfileobj(f, self.wfile)
					self.log_message("Sent file {file} as {mime}".format(file=file_path, mime=mime))
		except IOError:
			self.send_error(404, "File not found")
		except Exception as e:
			self.send_error(500, "Server Error: {!r}".format(e))

	def do_index(self, head):
		"""Ideally, this would simply accept JSON commands, following a well-defined API.
		The index page and rich UI would be served by a separate nginx/gunicorn/Django/
		jQuery/bootstrap server running on the same platform.
		"""
		file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "index.html"))
		try:
			with open(file_path, "r") as f:
				self.send_response(200)
				self.send_header("Content-type", "text/html")
				self.end_headers()
				if not head:
					self.writeutf8(f.read())
		except Exception as e:
			self.send_error(500, "Server Error: {!r}".format(e))

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
	daemon_threads=True

def web_server(server_class=ThreadingHTTPServer, handler_class=MyRequestHandler):
	server_address = ('', 80)
	httpd = server_class(server_address, handler_class)
	httpd.serve_forever()

# Rainbow larsen?
# Pixel chasing - one pixel per three or four which chases around the sequence
# Throb - fading in and out
# Twinkle - pixels brighten and fade randomly
# Snake / lightning - group of bright pixels thread through the sequence
# Alternative sequences - around the box on the outside? Another box in the middle?

def main():
	print("{0} is running.".format(sys.argv[0]))
	if neopixel:
		out = PixelsOut(GPIO_PIN)
	else:
		out = BitmapOut("test", single=True)

	t = threading.Thread(target=web_server)
	t.daemon = True
	t.start()

	routine = rainbow_cols
	while True:
		for timeout in routine():
			out.render()
			try:
				(op, value) = MESSAGE_QUEUE.get(block=True, timeout=timeout)
				if op == "routine":
					routine = value
					break
				elif op == "brightness":
					out.setBrightness(value)
				elif op == "colour":
					static.colour = value
			except queue.Empty:
				pass
	return 0

if __name__=='__main__':
	sys.exit(main())
