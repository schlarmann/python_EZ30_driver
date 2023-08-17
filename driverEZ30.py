#!/bin/python3

import argparse
import serial
import time
import math
import itertools
from PIL import Image, ImageOps, ImageDraw

class Driver:
	## Constants
	ANSWER_GOT_INSTRUCTION = b'\x00'	# Printer got instruction
	ANSWER_STATUS_DONE = b'\x20'		# Instruction Done
	ANSWER_PAUSE_DATA = b'\x40'			# Printer data buffer full
	ANSWER_STATUS_BUSY = b'\x80'		# Printer busy
	ANSWER_DROPPED_DATA = b'\xC0'		# Printer lost some bytes

	ANSWER_DISCOVERY = b'\x77'			# Expected Answer from printer after Discovery

	CMD_START = b'\x01' 				# Start Command ?

	CMD_IMAGE_SEQUENCE_START = b'\x03'	# Start image section, image n pixel long (n in next byte, image data in the following n bytes)

	CMD_HI_RES_INIT = b'\x05'			# ???-> Inits High res mode???
	CMD_LO_RES_INIT = b'\x06'			# ???-> Inits Low  res mode???

	CMD_Y_MOVE_RIGHT = b'\x07'			# Move n points to the right (n in next byte)
	CMD_Y_MOVE_LEFT = b'\x08'			# Move n points to the left (n in next byte) 

	CMD_HI_RES_SECOND_LINE = b'\x09'	# End of image section, moves half pixel down for higher x res (interlaced)
	CMD_LINE_FEED = b'\x0A'				# Move 1 line (8px) down
	CMD_HI_RES_LINEFEED = b'\x0B'		# Moves 1 line down, exits interlaced line
	CMD_FEED_LABEL_OUT = b'\x0C'		# Feeds label until the end

	CMD_HOME = b'\x0D'					# Homes print head

	CMD_INIT_SEQUENCE = b'\x0E\x80'		# Init sequence ???
	
	CMD_RESET = b'\x0f'					# Reset

	CMD_DISCOVERY = b'\x88' 			# Identify

	EZ30_BUF_SIZE = 0x5F # Determined empirically: send no stream of data until received 0xC0

	PRINTER_WIDTH = 108			# Width of printer
	#PRINTER_HEIGHT = 258			# Height of printer 
	PRINTER_HEIGHT = 255			# Height of printer 

	PRINTER_HI_RES_WIDTH = 216		# Width of printer in Hi Res mode 
	PRINTER_HI_RES_HEIGHT = 510		# Height of printer in Hi Res mode
	FACTOR_PREVIEW = 680/PRINTER_HI_RES_HEIGHT			# Scaling factor for the preview

	SERIAL_COMMAND_TIMEOUT = 10 # 10 seconds
	SERIAL_CHAR_DELAY = 0.0025 # (0.001 on laptop)

	## Variables
	curY = 0				# current y position
	curX = 0				# current x position
	serialPort = ""			# path to serial port
	ser = serial.Serial()	# Serial interface

	def _SerialInit(self):
		"""Initializes the serial port.
		Throws exception if port could not be opened"""
		# Baudrate required by printer
		self.ser.baudrate = 9600
		# Timeout
		self.ser.timeout = self.SERIAL_COMMAND_TIMEOUT
		try:
			self.ser.port = self.serialPort
			self.ser.open()
			self.ser.reset_input_buffer()
			self.ser.reset_output_buffer()
		except Exception as e:
			print("Could not open serial port: " + self.serialPort)
			raise e 
			exit()


	def _SendData(self, barrData, doACKCheck = True):
		"""Sends a bytearray to the printer.
		Makes a SERIAL_CHAR_DELAY long delay after each byte since the 
		printer needs time to process each byte"""

		self.ser.timeout = self.SERIAL_CHAR_DELAY

		for idx,data in enumerate(barrData):
			#self.ser.reset_input_buffer() # Clear all unread data
			dataByte = bytes([(data & 0xFF)])
			self.ser.write(dataByte)
			if(idx == 0):
				# "Command" -> expected Answer is 0x00
				self.ser.timeout = self.SERIAL_COMMAND_TIMEOUT

				serValue = self.ser.read(1)
				if(serValue == self.ANSWER_STATUS_DONE):
					doACKCheck = False
				elif(serValue != self.ANSWER_GOT_INSTRUCTION):
					raise ConnectionError("Did not ACK instruction, got "+str(serValue)+" instead")

				self.ser.timeout = self.SERIAL_CHAR_DELAY

			# Check for lost Data!
			serValue = self.ser.read(1)
			if(serValue and len(serValue) > 0):
				# Got data byte where we should not have
				
				if(serValue == self.ANSWER_PAUSE_DATA):
					
					self.ser.timeout = self.SERIAL_COMMAND_TIMEOUT
					serValue = 0xFF
					# Wait until we can send more data: -> read blocks!
					while(serValue != self.ANSWER_GOT_INSTRUCTION):
						buf = self.ser.read(1)
						if(buf and len(buf) > 0):
							serValue = buf
							if(serValue == self.ANSWER_DROPPED_DATA):
								raise ConnectionError("Dropped some data!")
						else:
							# Timeout
							raise ConnectionError("Did not get a continue in time!")
					self.ser.timeout = self.SERIAL_CHAR_DELAY

				elif(serValue == self.ANSWER_STATUS_DONE):
					doACKCheck = False
				else:
					print("Got unknown data packet during transmission: "+str(serValue))
		
		self.ser.timeout = self.SERIAL_COMMAND_TIMEOUT

		if(doACKCheck):
			serValue = 0xFF
			while(serValue != self.ANSWER_STATUS_DONE):
				buf = self.ser.read(1)
				if(buf and len(buf) > 0):
					serValue = buf
				else:
					# Timeout
					raise ConnectionError("Did not get an ACK in time!")
			

	def _DiscoverPrinter(self):
		"""Sends a discovery sequence to the printer and awaits a response.
		Throws exception if no answer was received"""
		self._SendData(self.CMD_START)
		self.ser.write(self.CMD_DISCOVERY)
		# Printer usually sends 3 bytes, the discovery answer being the last one
		retVal = self.ser.read(1)
		if(retVal != self.ANSWER_DISCOVERY):
			raise ConnectionAbortedError("No EZ30 printer connected to port \""+self.serialPort+"\"")
		self._SendData(self.CMD_RESET)

	def _MoveHeadY(self, absolutePos):
		"""Set absolute y direction of print head"""
		barrData = [0] * 2
		relativePos = abs(absolutePos-self.curY)
		# Check in which direction to move
		if(absolutePos >= self.curY):
			barrData[0] = self.CMD_Y_MOVE_RIGHT[0]
		else:
			barrData[0] = self.CMD_Y_MOVE_LEFT[0]
		barrData[1] = relativePos
		if(relativePos > 0):
			self._SendData(barrData)
			self.curY = absolutePos

	def _MoveHeadX(self, absolutePos):
		"""Set absolute x direction of print head"""
		if(absolutePos < self.curX):
			# Cant move upwards
			return -1;
		relativePos = absolutePos-self.curX
		for i in range(relativePos // 8):
			self._SendData(self.CMD_LINE_FEED)
		for i in range(relativePos % 8):
			self._SendData(self.CMD_HI_RES_SECOND_LINE)
		self.curX = absolutePos

	def _MoveHeadHome(self):
		"""Moves head back to home"""
		self._SendData(self.CMD_HOME)
		self.curY = 0

	def _MoveHead(self, X,Y):
		"""Sets x and y position of print head"""
		self._MoveHeadX(X)
		self._MoveHeadY(Y)

	def _MoveDown(self):
		"""Moves 1 line down"""
		self._SendData(self.CMD_HI_RES_LINEFEED)
		self._SendData(self.CMD_HI_RES_SECOND_LINE)

	def _InitEZ30(self):
		"""Initializes the EZ30 printer"""
		self._SendData(self.CMD_INIT_SEQUENCE)
		self._SendData(self.CMD_HOME)
		self._initResMode(True) # Standard Init in High res mode
		self.curX = 0
		self.curY = 0

	def _EndPrint(self):
		"""Feeds label out"""
		self._SendData(self.CMD_HOME)
		self._SendData(self.CMD_FEED_LABEL_OUT)

	def _PrintImageLine(self, barrImageData, length):
		"""Prints one line of image data"""
		# Have to send start byte and length as well
		barrLength = length + 1 + len(self.CMD_IMAGE_SEQUENCE_START)
		barrData = [0] * barrLength
		barrData[0] = self.CMD_IMAGE_SEQUENCE_START[0]
		barrData[1] = length
		# Copy image data
		for i in range (length):
			barrData[2+i] = barrImageData[i]
		# Increment current y position
		self.curY += length
		self._SendData(barrData)

	def _ResizeImage(self,image, isHighRes: bool = False):
		"""Resizes the passed image to fit on the label.
		Returns resized image object"""

		if(isinstance(image, str)):
			img = Image.open(image)
		elif(isinstance(image, Image.Image)):
			img = image
		else:
			raise ValueError("image parameter is neither a string nor an Image object!")

		maxWidth = self.PRINTER_WIDTH
		maxHeight = self.PRINTER_HEIGHT
		if(isHighRes):
			maxWidth = self.PRINTER_HI_RES_WIDTH
			maxHeight = self.PRINTER_HI_RES_HEIGHT

		imgWidth = img.size[0]
		imgHeight = img.size[1]
		
		# resize the image
		newHeight = int( (maxWidth / imgWidth) * imgHeight)
		if(newHeight > maxHeight):
			newHeight = maxHeight
			#raise ValueError("Image \""+image+"\" is too tall!")
		newImg = img.resize((maxWidth, newHeight))

		return newImg

	def _initResMode(self, isHighRes:bool = False):
		if isHighRes:
			self._SendData(self.CMD_HI_RES_INIT)
		else:	
			self._SendData(self.CMD_LO_RES_INIT)

	def _ConvertImageTo1bppx(self,img, threshold):
		"""Converts the image object "img" to a 1bppx array.
		Returns this array as well as the size of the image"""

		bgImage = Image.new("RGBA", img.size, color=255)
		bgImage.paste(img)

		# Convert image to greyscale
		greyImg = bgImage.convert("L", dither=None)
		# B&W image is inverted
		bwImg = greyImg.point((lambda p: p<threshold),mode="1")

		# Get array with pixel data(array with the 3 rgb values)
		pixels = list(bwImg.getdata())
		
		imgWidth = img.size[0]
		imgHeight = img.size[1]

		return pixels, imgWidth, imgHeight

	def _Convert1bppxImageToEZ30Data(self, pixelData, imgWidth, imgHeight, isHighRes: bool = False):
		"""Converts the 1bppx image in pixelData into the line by line representation 
		needed by the EZ30 printer.
		Returns an array containing an array for each line"""
		ez30ImageData = []

		# Array fuckery...
		# Print head is in x direction, so each byte must contain 8 bits "downwards" the image
		# Calculation is a bit messy...
		if(isHighRes):
			for i in range( (imgHeight + 15) // 16):
				rowNum = i * 16
				row = []
				# 'even' field
				for j in range(imgWidth):
					dataByte = 0
					for k in range(0,16,2):
						try:
							dataByte += pixelData[(rowNum+k)*imgWidth + j] << ((k)//2)
						except:
							dataByte += 0
					row.append(dataByte)
				ez30ImageData.append(bytearray(row))
				# 'odd' field
				row = []
				for j in range(imgWidth):
					dataByte = 0
					for k in range(1,16,2):
						try:
							dataByte += pixelData[(rowNum+k)*imgWidth + j] << ((k-1)//2)
						except:
							dataByte += 0
					row.append(dataByte)
				ez30ImageData.append(bytearray(row))
		else:
			for i in range( (imgHeight + 7) // 8):
				rowNum = i * 8
				row = []
				for j in range(imgWidth):
					dataByte = 0
					for k in range(8):
						try:
							dataByte += pixelData[(rowNum+k)*imgWidth + j] << k
						except:
							dataByte += 0
					row.append(dataByte)
				ez30ImageData.append(bytearray(row))
		return ez30ImageData

	def _ConvertImage(self, image, threshold: int, isHighRes: bool = False):
		"""Converts image to EZ30 format
		image{str||Image}: 	Path to the image file or Image object that should be printed on the label
		threshold{int}:		Threshold for converting the image to 1bppx"""
		# convert image to a list of pixels
		
		resizedImage = self._ResizeImage(image, isHighRes)
		pixelData, imgWidth, imgHeight = self._ConvertImageTo1bppx(resizedImage, threshold)
		ez30ImageData = self._Convert1bppxImageToEZ30Data(pixelData, imgWidth, imgHeight, isHighRes)
		return ez30ImageData	

	def _ConvertToLines(self, imageData, isHighRes: bool = False):
		"""Converts imageData to line Data separated by white spaces (mostly black pixels, with pixel offset)"""
		lineData = []

		kFunc = lambda val: val != 0
		"""lineData object format: {offs: int, length: int, data: []} offset: where to move the head to. len: how many bytes are in data"""
		for row in imageData:
			currentOffset = 0
			lastWhiteSegEnd = 0
			currentLineData = []
			for kVal, group in itertools.groupby(row, kFunc):
				pixelData = bytearray(group)
				currentOffset += len(pixelData)
				if kVal == False:
					# Segment of white pixels
					lastWhiteSegEnd = currentOffset

				else:
					# Segment of colored pixels
					currentLineData.append({"offs": lastWhiteSegEnd, "length": len(pixelData), "data": pixelData})
					pass

			lineData.append(currentLineData)
	
		# remove empty arrays at the end (so we dont print them)
		return list(reversed(tuple(itertools.dropwhile(lambda x: x == [], reversed(lineData)))))

	def __init__(self, port):
		"""Initializes the printer driver
		port{str}: 		Path to the serial port where the printer is connected(eg /dev/ttyS0 on Linux or COM1 on Windows)"""
		self.curY = 0				# current y position
		self.curX = 0				# current x position
		self.serialPort = port		# path to serial port
		self.ser = serial.Serial()	# Serial interface

	def InitPrinter(self):
		"""Initializes the printer"""
		# Initialize the serial port
		self._SerialInit()
		# Check if a printer is connected to the serial port
		self._DiscoverPrinter()
		# Initialize the printer
		self._InitEZ30()

		# Wait for init
		time.sleep(1)

		# Print one empty line to flush out garbage data in printer
		row = [0] * self.PRINTER_HI_RES_WIDTH
		self._PrintImageLine(row, len(row))
		self._MoveHeadHome()

	def PrintLabelOld(self, image, threshold: int, isHighRes: bool = False):
		"""Prints a label
		image{str||Image}: 	Path to the image file or Image object that should be printed on the label
		threshold{int}:		Threshold for converting the image to 1bppx"""
		imageData = self._ConvertImage(image, threshold, isHighRes)
		self._initResMode(isHighRes)
		self._MoveHeadHome()
		# Print image row by row
		for idx,row in enumerate(imageData):
			self._MoveHeadY(0)
			time.sleep(0.1)
			self._PrintImageLine(row, len(row))
			if(isHighRes and (idx & 1)==1):
				self._SendData(self.CMD_HI_RES_LINEFEED)
			elif(isHighRes):
				self._SendData(self.CMD_HI_RES_SECOND_LINE)
			else:
				self._MoveDown()

		self._EndPrint()

	def PrintLabel(self, image, threshold: int, isHighRes: bool = False):
		"""Prints a label faster!
		image{str||Image}: 	Path to the image file or Image object that should be printed on the label
		threshold{int}:		Threshold for converting the image to 1bppx"""
		imageData = self._ConvertImage(image, threshold, isHighRes)
		self._initResMode(isHighRes)
		self._MoveHeadHome()

		if(isHighRes):
			self._MoveHeadY(self.PRINTER_HI_RES_WIDTH)
		else:
			self._MoveHeadY(self.PRINTER_WIDTH)
		self._MoveHeadY(0)

		allLinesData = self._ConvertToLines(imageData, isHighRes)
		for lineIdx, lineData in enumerate(allLinesData):
			if(len(lineData) > 0):
				# Actual printing
				for segment in lineData:
					self._MoveHeadY(segment["offs"])
					self._PrintImageLine(segment["data"], segment["length"])
			# Move print head
			if(isHighRes and (lineIdx & 1)==1):
				self._SendData(self.CMD_HI_RES_LINEFEED)
			elif(isHighRes):
				self._SendData(self.CMD_HI_RES_SECOND_LINE)
			else:
				self._MoveDown()
			time.sleep(0.1)

		self._EndPrint()


	def PreviewLabel(self, image, threshold: int, isHighRes: bool = False):
		"""Generates a preview image of the label
		image{str||Image}: 	Path to the image file or Image object that should be printed on the label
		threshold{int}:		Threshold for converting the image to 1bppx
		Returns the preview image object"""
		resizedImage = self._ResizeImage(image, isHighRes)
		# enlarge image to make it look more like on the actual label
		resizedImage = resizedImage.resize((resizedImage.size[0], int(resizedImage.size[1] * self.FACTOR_PREVIEW)) )
		pixelData, imgWidth, imgHeight = self._ConvertImageTo1bppx(resizedImage, threshold)

		imgHeight = math.floor(imgHeight * self.FACTOR_PREVIEW)
		newImg = Image.new("1", (imgWidth, imgHeight))
		newImg.putdata(pixelData)
		bwImg = newImg.point((lambda p: p!=1),mode="1")


		newImg = bwImg.resize((imgWidth, imgHeight))

		maxWidth = self.PRINTER_WIDTH
		maxHeight = self.PRINTER_HEIGHT
		if(isHighRes):
			maxWidth = self.PRINTER_HI_RES_WIDTH
			maxHeight = self.PRINTER_HI_RES_HEIGHT
		scaleImg = Image.new("1", (maxWidth, math.floor(maxHeight * self.FACTOR_PREVIEW) ))
    	#center = (int(0.5 * maxWidth), int(0.5 * maxHeight))
		ImageDraw.floodfill(scaleImg, xy=(0,0), value=1)
		scaleImg.paste(newImg)
		scaleImg = scaleImg.rotate(90, expand=True)
		if(not isHighRes): # Scale low res preview to same size as high res one
			scaleImg = scaleImg.resize((math.floor(self.PRINTER_HI_RES_HEIGHT * self.FACTOR_PREVIEW), self.PRINTER_HI_RES_WIDTH ))
		return scaleImg
