#!/usr/bin/env python3

"""
Listens to commands via HTTP for controlling a simple Christmas ornament.

 0 0 0 0 0   0 00001 111 11  111122222  22 2 2 23
 0 1 2 3 4   5 67890 123 45  678901234  56 7 8 90
 | | | | |   | ||||| ||| ||  |||||||||  || | | ||
04      05    13        21      30        42   43 - y=0
  03  06    12 14     20 22    2931     41        - y=1
	02      11  15   19  23   28  32        40    - y=2
  01  07    10   16 18   24  27 33 34  36      39 - y=3
00      08  09    17     25 26      35    37  38  - y=4
"""

from PIL import Image, ImageDraw
import colorsys
import http.server
import json
import queue
import random
import sys
import threading
import time

TIMEOUT = 0.2

class Pixel(object):
	def __init__(self, chain_pos, x, y):
		self.chain_pos = chain_pos
		self.x = x
		self.y = y
		self.r = 0xFF
		self.g = 0
		self.b = 0

	def rgb(self):
		return ((self.g << 16) | (self.r << 8) | (self.b << 0))

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
	(4,  0),
	(3,  1),
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

	def render(self, pixels):
		"""Given a collection of pixels, produces a bitmap.
		"""
		im = Image.new("RGB", (self.X_HEIGHT, self.Y_HEIGHT), "grey")
		draw = ImageDraw.Draw(im)
		for p in pixels:
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

class PixelsOut:
	def __init__(self, gpio_pin):
		print("Creating pixel output, GPIO={0}".format(gpio_pin))
		self.gpio_pin = gpio_pin

	def render(self, pixels):
		"""Gets the C library to bash the pixels
		out over DMA/PWM.
		"""
		pass

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

def snowflakes(steps=100):
	"""All red, with falling white pixels representing snow.

	@todo make snow 2x2, as 1x1 doesn't show up well in most columns.
	"""
	def render_snow(cols, flakes, flake_chance):
		new_flakes = []
		for (x,y) in flakes:
			if y < 3:
				print("flake at ({},{})->({},{})".format(x, y, x, y+1))
				new_flakes.append((x, y + 1))

		if random.random() < flake_chance:
			col = random.randrange(0, len(cols))
			print("New flake in col {}".format(col))
			new_flakes.append((col, 0))

		for col in cols:
			for pixel in col:
				if (pixel.x, pixel.y) in new_flakes:
					print("Found flake at {},{}".format(pixel.x, pixel.y))
					pixel.set(0xff, 0xff, 0xff)
				else:
					pixel.set(0xff, 0, 0)
		return new_flakes

	flakes = []
	for i in range(0, steps):
		flakes = render_snow(COLS, flakes, 0.7)
		yield TIMEOUT

def rainbow(steps=100):
	"""Generate a rainbow pattern which rotates.
	"""
	for i in range(0, steps):
		for (idx, li) in enumerate(COLS):
			r,g,b = generate_colour(idx, len(COLS), 1-i/steps)
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
		yield
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
		print("Got body: {body!r}".format(body=post_body))
		try:
			post_body = post_body.decode("utf-8")
			(key, value) = post_body.split("=")
			routine = {
				"rainbow": rainbow,
				"larsen": larsen,
				"snowflakes": snowflakes
			}[value]
			MESSAGE_QUEUE.put(routine)
			self.send_response(200)
			self.send_header("Content-type", "application/json")
			self.end_headers()
			self.writeutf8('{ "status": "OK" }');
		except Exception as e:
			self.send_response(500)
			self.send_header("Content-type", "text/plain")
			self.end_headers()
			self.writeutf8('Internal Server Error: {}'.format(e));

	def do_REQ(self, head):
		if self.path == "/":
			self.do_index(head)
		else:
			self.send_response(404)
			self.send_header("Content-type", "text/plain")
			self.end_headers()
			self.writeutf8("Page not found!")

	def writeutf8(self, string):
		self.wfile.write(string.encode("utf-8"))

	def do_index(self, head):
		"""Ideally, this would simply accept JSON commands, following a well-defined API.
		The index page and rich UI would be served by a separate nginx/gunicorn/Django/
		jQuery/bootstrap server running on the same platform.
		"""
		with open("index.html", "r") as f:
			self.send_response(200)
			self.send_header("Content-type", "text/html")
			self.end_headers()
			if not head:
				self.writeutf8(f.read())

def web_server(server_class=http.server.HTTPServer, handler_class=MyRequestHandler):
	server_address = ('', 8000)
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
	bo = BitmapOut("test", single=True)

	t = threading.Thread(target=web_server)
	t.daemon = True
	t.start()

	routine = rainbow
	while True:
		for timeout in routine():
			bo.render(PIXELS)
			try:
				routine = MESSAGE_QUEUE.get(block=True, timeout=timeout)
				break
			except queue.Empty:
				pass
	return 0

if __name__=='__main__':
	sys.exit(main())
