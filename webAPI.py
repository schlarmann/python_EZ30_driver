import argparse
import driverEZ30
import json
import base64
from io import BytesIO 
from PIL import Image
from flask import Flask, request, jsonify
from threading import Thread
import queue
import time

EZ30_TTY_PORT = "/dev/ttyUSB0"

STATUS_UPLOADED = 0
STATUS_START_PRINT = 10
STATUS_DONE = 20
STATUS_PRINT_FAILED = -10
STATUS_ALREADY_PRINTING = -20

# set to True if you want to test without a printer connected
IS_DUMMY = False

labelArray = {}
printQueue = queue.Queue()
labelLifetime = 60*60

app = Flask(__name__)
@app.route('/uploadLabel', methods = ['POST'])
def uploadLabel():
    global labelArray
    if request.method == 'POST':
        threshold = int(request.form.get('threshold', 127))
        isHighRes = False
        if('isHighRes' in request.form):
            isHighRes = True
        imageFile = request.files['imageData']
        imageDataB64 = base64.b64encode(imageFile.read())
        if(imageDataB64 == ''):
            retVal = {"status":"Please provide an image file in \"imageData\"", "statusId":-1}
            return json.dumps(retVal),400
        try:
            im = Image.open(BytesIO(base64.b64decode(imageDataB64))) 
        except Exception as e:
            retVal = {"status":"Image could not be parsed properly!", "error":str(e), "statusId":-1}
            return json.dumps(retVal),400
        else:
            labelId = hex(hash(imageDataB64)+threshold+isHighRes*1234)[:-9:-1] # last 8 hex digits of the hash
            labelArray[labelId] = {'threshold':threshold, 'printCount': 0, 'isHighRes': isHighRes, 'imageDataB64':imageDataB64, 'status':"Uploaded", 'statusId':STATUS_UPLOADED, 'timestamp':time.time()}
            retVal = {"labelId":labelId}
            return json.dumps(retVal),200
       
@app.route('/<string:labelId>/rotateLabel', methods = ['POST'])
def rotateLabel(labelId):
    global labelArray
    if request.method == 'POST':
        if( labelId not in labelArray ):
            retVal = {"status":"Invalid label id!", "statusId":-1}
            return json.dumps(retVal),400
        imageDataB64 = labelArray[labelId]['imageDataB64']
        try:
            im = Image.open(BytesIO(base64.b64decode(imageDataB64))) 
            convImg = im.rotate(90, expand=True)
            buffer = BytesIO()
            convImg.save(buffer,format="PNG")
            myimage = buffer.getvalue()   
            labelArray[labelId]['imageDataB64'] = base64.b64encode(myimage)
            labelArray[labelId]['timestamp'] = time.time()
            retVal = {"status":"Image rotated 90 degrees", "statusId":labelArray[labelId]['statusId']}
            return json.dumps(retVal),200
        except Exception as e:
            retVal = {"status":"Image could not be parsed properly!", "error":str(e), "statusId":labelArray[labelId]['statusId']}
            return json.dumps(retVal),400

@app.route('/<string:labelId>/setThreshold', methods = ['POST'])###
def setThreshold(labelId):
    global labelArray
    if request.method == 'POST':
        if( labelId not in labelArray ):
            retVal = {"status":"Invalid label id!", "statusId":-1}
            return json.dumps(retVal),400
        threshold = int(request.form.get('threshold'))
        try:
            labelArray[labelId]['threshold'] = threshold
            retVal = {"status":"Threshold set to: {}".format(threshold), "statusId":labelArray[labelId]['statusId']}
            labelArray[labelId]['timestamp'] = time.time()
            return json.dumps(retVal),200
        except Exception as e:
            retVal = {"status":"Label array could not be read", "error":str(e), "statusId":labelArray[labelId]['statusId']}
            return json.dumps(retVal),400

@app.route('/<string:labelId>/previewLabel', methods = ['GET'])
def previewLabel(labelId):
    global labelArray
    if request.method == 'GET':
        if( labelId not in labelArray ):
            retVal = {"status":"Invalid label id!", "statusId":-1}
            return json.dumps(retVal),400
        threshold = labelArray[labelId]['threshold']
        isHighRes = labelArray[labelId]['isHighRes']
        imageDataB64 = labelArray[labelId]['imageDataB64']
        try:
            im = Image.open(BytesIO(base64.b64decode(imageDataB64))) 
            convImg = ez30.PreviewLabel(im, threshold, isHighRes)
            buffer = BytesIO()
            convImg.save(buffer,format="PNG")
            myimage = buffer.getvalue()   
            labelArray[labelId]['timestamp'] = time.time()
            return myimage,200
        except Exception as e:
            print(e)
            retVal = {"status":"Image could not be parsed properly!", "error":str(e), "statusId":labelArray[labelId]['statusId']}
            return json.dumps(retVal),400

@app.route('/<string:labelId>/getStatus', methods = ['GET'])
def getStatus(labelId):
    global labelArray
    if request.method == 'GET':
        if( labelId not in labelArray ):
            retVal = {"status":"Invalid label id!", "statusId":-1}
            return json.dumps(retVal),400
        retVal = {"status":labelArray[labelId]['status'], "statusId":labelArray[labelId]['statusId']}
        labelArray[labelId]['timestamp'] = time.time()
        return json.dumps(retVal),200

@app.route('/<string:labelId>/deleteLabel', methods = ['POST'])
def deleteLabel(labelId):
    global labelArray
    if request.method == 'POST':
        if( labelId not in labelArray ):
            retVal = {"status":"Invalid label id!", "statusId":-1}
            return json.dumps(retVal),400
        oldStatusId = labelArray[labelId]['statusId']
        labelArray.pop(labelId)
        retVal = {"status":"Deleted!", "statusId":oldStatusId}
        return json.dumps(retVal),200

@app.route('/<string:labelId>/printLabel', methods = ['POST'])
def printLabel(labelId):
    global labelArray
    if request.method == 'POST':
        if( labelId not in labelArray ):
            retVal = {"status":"Invalid label id!", "statusId":-1}
            return json.dumps(retVal),400
        threshold = labelArray[labelId]['threshold']
        imageDataB64 = labelArray[labelId]['imageDataB64']
        count = int(request.form.get('printCount', 1))
        if(count > 5):
            count = 5
        if(count < 1):
            count = 1
        try:
            labelArray[labelId]['status'] = "Starting print!"
            labelArray[labelId]['statusId'] = STATUS_START_PRINT
            labelArray[labelId]['printCount'] = count
            printQueue.put(labelId)
            retVal = {"status":"Starting Print!", "statusId":labelArray[labelId]['statusId']}
            labelArray[labelId]['timestamp'] = time.time()
            return json.dumps(retVal),200
        except Exception as e:
            print(e)
            retVal = {"status":"Image could not be parsed properly!", "error":str(e), "statusId":labelArray[labelId]['statusId']}
            return json.dumps(retVal),400

@app.after_request
def after_request(response):
    header = response.headers
    header['Access-Control-Allow-Origin'] = '*'
    return response

def printLabelThread(labelQueue):
    while True:
        time.sleep(1)
        if not labelQueue.empty():
            labelId = labelQueue.get()
            print("Starting print of label: "+str(labelId))
            try:
                threshold = labelArray[labelId]['threshold']
                isHighRes = labelArray[labelId]['isHighRes']
                imageDataB64 = labelArray[labelId]['imageDataB64']
                im = Image.open(BytesIO(base64.b64decode(imageDataB64))) 
                if not IS_DUMMY:
                    ez30.PrintLabel(im, threshold, isHighRes)
                labelArray[labelId]['printCount'] -= 1
                labelArray[labelId]['status'] = "Print Done!"
                labelArray[labelId]['statusId'] = STATUS_DONE
                if labelArray[labelId]['printCount'] > 0:
                    labelQueue.put(labelId)
            except Exception as e:
                print(e)
                labelArray[labelId]['status'] = "Printing failed with exception: "+str(e)
                labelArray[labelId]['statusId'] = STATUS_PRINT_FAILED
            finally:
                labelQueue.task_done()

def garbageCollectionThread():
    """Removes all labels older than `labelLifetime` from the `labelArray`"""
    while True:
        expiredLabels = []
        for labelId,label in enumerate(labelArray):
            if(label['timestamp'] - time.time() > labelLifetime):
                expiredLabels.append(labelId)
        for labelId in expiredLabels:
            labelArray.pop(labelId)
        time.sleep(labelLifetime)

if __name__ == '__main__':
    ez30 = driverEZ30.Driver(EZ30_TTY_PORT)
    if not IS_DUMMY:
        ez30.InitPrinter()
    pLT = Thread(target=printLabelThread,args=(printQueue,))
    pLT.start()
    gCT = Thread(target=garbageCollectionThread,args=())
    gCT.start()
    app.run(host='0.0.0.0', port=1050)
