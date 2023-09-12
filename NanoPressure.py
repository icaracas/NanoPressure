
import sys
import time
import struct
import logging
import argparse
import asyncio
import numpy as np
from datetime import datetime,timedelta
from signal import SIGINT, SIGTERM

from bleak import BleakScanner, BleakClient, BleakGATTCharacteristic
from simple_term_menu import TerminalMenu

#Global logger
log = logging.getLogger(__name__)

def deviceKey(device):
    '''Define a key from a device'''
    return  f'\"{device.complete_name}\" ({device.address.string})'

async def discoverDevice(timeout, minimum_rssi):
    '''Get a bluetooth connection'''

    log.info("Scanning for bluetooth devices...")
    devices = await BleakScanner.discover(timeout=timeout,return_adv=True)

    #remove devices with too low rssi
    devices = { addr : (device, adv) for addr, (device, adv)  in devices.items() if  adv.rssi > minimum_rssi}

    #Report
    for device, adv in devices.values():
        log.info(f"Found device {device} (RSSI = {adv.rssi} dB)")
    
    #Check if we have any devices
    if not devices:
        log.error("Could not find any devices, check minimum RSSI level (option: --rssi)")
        sys.exit(1)

    #if we only have on device, use that
    if len(devices) == 1:
        device , _ = next(iter(devices.values()))
    #otherwise have the user select
    else:
        devlist = [device for device, adv in devices.values()]
        terminal_menu = TerminalMenu([str(dev) for dev in devlist], title="Please select your device:")
        menu_entry_index = terminal_menu.show()
        device = devlist[menu_entry_index]

    return device

async def getDevice(address, timeout):
    '''Find the device by the given address'''
    device = await BleakScanner.find_device_by_address(address, timeout=timeout)
    
    if not device:
        log.error(f"Could not find device with address {address}")
        sys.exit(1)

    return device


def scanPressureCallback(sender: BleakGATTCharacteristic, data: bytearray):
    '''Scan current pressure values'''
    pressure = struct.unpack('f', data)[0]
    print(f"{datetime.now()} : {pressure:10.2f} Pa",end=eol)

async def readCounts(client: BleakClient, handle: int):
    '''Read number of buffered pressure values'''     
    counts = await client.read_gatt_char(handle)
    counts = struct.unpack('<I',counts)[0]
    log.info(f"Found {counts} pressure values on device")
    return counts


async def loop(args: argparse.Namespace):
    '''Main program loop'''

    #Device characteristics handles. Needs to be updated if device characteristics are changed!
    handles = { 'pressureValue'  : 11,
                'interval'       : 16,
                'pressureHistory': 20,
                'deviceTime'     : 23,
                'pressureCounts' : 26 }

    #Get a device
    if args.addr:
        device = await getDevice(address=args.addr, timeout=args.timeout)
    else:
        device = await discoverDevice(timeout=args.timeout,minimum_rssi=args.rssi)

    assert device
    log.info(f"Using device {device}")

    #Connect to the device
    async with BleakClient(device, timeout=args.timeout) as client:
        log.info(f"Connected to device {device}")
        
        #For debugging only
        for service in client.services:
             log.debug("Service %s", service)
             for char in service.characteristics:
                log.debug(f"Characteristics {char} | {char.properties}")
        
        #Set readout interval if requested
        if args.interval is not None:
            data = await client.read_gatt_char(handles['interval'])
            log.info(f"Current readout interval is {struct.unpack('<I',data)[0]} second(s)")
            log.info(f"Setting readout interval to {args.interval} second(s)")
            await client.write_gatt_char(handles['interval'],struct.pack('<I',args.interval),response=True)
            
            #Also look at current counts to see how much buffer time is left
            curr_counts = await client.read_gatt_char(handles['pressureCounts'])
            curr_counts = struct.unpack('<I',curr_counts)[0]
            counts_left = 16384 - curr_counts
            intv = args.interval if args.interval else 0.1
            log.warning(f"Remaining recording buffer will last for {timedelta(seconds=counts_left*intv)}")


        #See which mode we want to operate in
        #Scan mode -- show all newly appearing values
        if args.mode=='scan':
            log.info('Starting scanning mode...')
            #Set a gloabl end-of-line 
            global eol
            eol = '\n' if args.newline else '\r'

            #Start scanning
            await client.start_notify(handles['pressureValue'], scanPressureCallback)
            
            #Make current loop stop gracefully on keyboard interrupt
            loop = asyncio.get_event_loop()
            stopEvent = asyncio.Event()
            for signal_enum in [SIGINT, SIGTERM]:
                loop.add_signal_handler(signal_enum, stopEvent.set)
            await stopEvent.wait()
            await client.stop_notify(handles['pressureValue'])
        
        #Download mode -- read all values stored on device
        elif args.mode=='download':
            log.info('Starting download mode...')
            
            #start with empty data list
            dataList = []
            
            #Get current counts
            counts = await readCounts(client,handles['pressureCounts'])

            #Read as long as there is data on the device
            start = time.time()
            while counts > 0:
    
                #Read all the counts that we already know about
                for i in range(counts):
                    data = await client.read_gatt_char(handles['pressureHistory'])
                    dataList += [struct.unpack('<fI',data)]
                    print(f"Reading {len(dataList):10d} of {counts}",end='\r')

                #See if there are new counts that have appeared
                counts = await readCounts(client,handles['pressureCounts'])

            stop = time.time()
            log.info(f"Read {len(dataList)} values in {stop-start} seconds") 


            localTime = time.time()
            deviceTime = await client.read_gatt_char(handles['deviceTime'])
            deviceTime = float(struct.unpack('<I',deviceTime)[0])/1000.
            deltaTime = localTime-deviceTime
            log.info(f"Established time Difference of {deltaTime} seconds.")
            log.info(f"Device was started at {datetime.fromtimestamp(deltaTime)}.")

            #Convert to numpy array
            data = np.array(dataList)
            #convert milliseconds to seconds
            data[:,1] /= 1000
            #add time offset to get actual time
            data[:,1] += deltaTime
            
            #Open file in proper mode
            with open(args.filename,'w' if args.overwrite else 'a') as outfile:
                np.savetxt(outfile,data,fmt='%.2f')
            
            
            
    log.info(f"Disconnected from device {device}")



if __name__ == '__main__':
    
    #Parse commandline arguments
    parser = argparse.ArgumentParser(description='''Readout Arduino NanoPressure
                                     device by Bluetooth.''')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Set verbosity level')
    parser.add_argument('--mode', default='scan', choices=['scan', 'download'],
                        help='Scan pressure values or download recorded values (default=%(default)s)')
    parser.add_argument('--addr', type=str,
                        help='UUID of device to connect to (format = XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX)')    
    parser.add_argument('--rssi', default=-80, type=int,
                        help='Minimum bluetooth signal strength in dB (default=%(default)i')
    parser.add_argument('--timeout', default=5, type=int,
                        help='Timeout for scanning bluetooth devices in seconds (default=%(default)u)')
    parser.add_argument('-i','--interval', type=int,
                        help='If given, set readout interval in seconds. 0 = as fast as possible.')
    parser.add_argument('-n','--newline', default=False, action='store_true',
                        help='Print a newline after each pressure reading (default=%(default)s)')
    parser.add_argument('-f','--filename', default='pressure.txt',
                        help='The filename in which to store the data (default=%(default)s)')
    parser.add_argument('-o','--overwrite', default=False, action='store_true',
                        help='Overwrite instead of appending to existing data file (default=%(default)s)')

    args = parser.parse_args()

    #setup logging
    loglvls = {0 : logging.ERROR,
               1 : logging.WARN,
               2 : logging.INFO,
               3 : logging.DEBUG}
    logging.basicConfig(format='[%(levelname)07s]: %(message)s',
                        level=loglvls[args.verbose])

    #Run the main routine
    asyncio.run(loop(args))
 
