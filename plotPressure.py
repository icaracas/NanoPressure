
import logging
import argparse
import numpy as np
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
#Turn of offset substration on axis labels
plt.rcParams['axes.formatter.useoffset'] = False


#Global logger
log = logging.getLogger(__name__)

if __name__ == '__main__':
    
    #Parse commandline arguments
    parser = argparse.ArgumentParser(description='''Readout Arduino NanoPressure
                                     device by Bluetooth.''')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Set verbosity level')
    parser.add_argument('filename', nargs='+', default='pressure.txt',
                        help='The filename from which to read the data (default=%(default)s)')
    parser.add_argument('-o','--outfile', default=None, required=False,
                        help='The filename of the generated plot (default=same as filename)')
    parser.add_argument('--pascal', dest='pascal', default=False, action='store_true',
                        help='Use pascals as units instead of millibars')

    args = parser.parse_args()


    #setup logging
    loglvls = {0 : logging.ERROR,
               1 : logging.WARN,
               2 : logging.INFO,
               3 : logging.DEBUG}
    logging.basicConfig(format='[%(levelname)07s]: %(message)s',
                        level=loglvls[args.verbose])

    #Create the figure
    plt.figure(figsize=(10,4))

    for fname in args.filename:

        #Read in the data
        pressures,times = np.loadtxt(fname).T
        log.info(f'Read {len(times)} data values from "{fname}"')

        #Convert to datetime objects
        log.debug(f'Converting millisecond times to datetime objects')
        times = [datetime.fromtimestamp(time) for time in times]

        #Convert to mbars by default
        if not args.pascal:
            pressures /= 100.
            plabel = 'Pressure [mbar]'
        else:
            plabel = 'Pressure [Pa]'

        #Add the data to the plot
        plt.plot(times,pressures,'o-',label=fname.replace('.txt',''))

    plt.legend(frameon=False)
    plt.ylabel(plabel)
    plt.xlabel('Time')
    plt.tight_layout()

    #Generate output filename
    if not args.outfile:
        args.outfile = "-".join(args.filename).replace('.txt','')+'.png'
    log.info(f'Writing to file "{args.outfile}"')
    plt.savefig(args.outfile,dpi=200)
    

