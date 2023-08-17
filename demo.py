#!/bin/python3

import argparse
import driverEZ30
from PIL import Image

if __name__ == "__main__": # Main

	# Arguments for the program
	parser = argparse.ArgumentParser(description='Prints a given image file on a Seiko EZ30 label printer')
	parser.add_argument('-i', '--image',
		            dest='imageFile',
		            help='Image file to print',
			    required=True,
		            type=str
		            )
	parser.add_argument('-p', '--port',
		            default='/dev/ttyUSB0',
		            dest='port',
		            help='Provide serial port where printer is connected',
		            type=str
		            )
	parser.add_argument('-t', '--threshold',
		            default=127,
		            dest='threshold',
		            help='Black threshold for 1bppx conversion',
		            type=int
		            )
	parser.add_argument('--preview',
		            dest='preview',
			    action="count",
		            help='Shows 1bppx image instead of printing it'
		            )
	parser.add_argument('--hi-res',
		            dest='hires',
			    action="count",
		            help='Prints in high resolution mode (doubles x and y resolution)'
		            )
	args = parser.parse_args()

	isHighResolution = True
	if(args.hires == None):
		isHighResolution = False

	ez30 = driverEZ30.Driver(args.port, isHighResolution)

	if(args.preview == None):
		# preview not set -> not in parameter list -> print image
		ez30.InitPrinter()
		ez30.PrintLabel(args.imageFile, args.threshold)

	else:
		ez30.PreviewLabel(args.imageFile, args.threshold).show()

