#
# rtlsdr_scan
#
# http://eartoearoak.com/software/rtlsdr-scanner
#
# Copyright 2012 - 2015 Al Brown
#
# A frequency scanning GUI for the OsmoSDR rtl-sdr library at
# http://sdr.osmocom.org/trac/wiki/rtl-sdr
#
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from collections import OrderedDict
import datetime
import glob
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from pickle import dump, load, UnpicklingError, PickleError

from PIL import Image
import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
import wx

from rtlsdr_scanner.constants import APP_NAME
from rtlsdr_scanner.misc import format_iso_time
from rtlsdr_scanner.spectrum import create_mesh, sort_spectrum


def bs(s):
    return bytes(s, encoding="utf-8")


class File:
    class Types:
        SAVE, PLOT, IMAGE, GEO, GMAP, TRACK, CONT = range(7)

    class SaveType:
        RFS = 0

    class PlotType:
        CSV, GNUPLOT, FREEMAT, WWB = range(4)

    class ImageType:
        BMP, EPS, GIF, JPEG, PDF, PNG, PPM, TIFF = range(8)

    class GeoType:
        KMZ, CSV, BMP, EPS, GIF, JPEG, PDF, PNG, PPM, TIFF = range(10)

    class GMapType:
        HTML = 0

    class TrackType:
        GPX = 0

    SAVE = [''] * 1
    SAVE[SaveType.RFS] = 'RTLSDR frequency scan (*.rfs)|*.rfs'

    PLOT = [''] * 4
    PLOT[PlotType.CSV] = "CSV table (*.csv)|*.csv"
    PLOT[PlotType.GNUPLOT] = "gnuplot script (*.plt)|*.plt"
    PLOT[PlotType.FREEMAT] = "FreeMat script (*.m)|*.m"
    PLOT[PlotType.WWB] = "Wireless Workbench (*.sdb2)|*.sdb2"

    IMAGE = [''] * 8
    IMAGE[ImageType.BMP] = 'Bitmap image (*.bmp)|*.bmp'
    IMAGE[ImageType.EPS] = 'Encapsulated PostScript (*.eps)|*.eps'
    IMAGE[ImageType.GIF] = 'GIF image (*.gif)|*.gif'
    IMAGE[ImageType.JPEG] = 'JPEG image (*.jpeg)|*.jpeg'
    IMAGE[ImageType.PDF] = 'Portable Document (*.pdf)|*.pdf'
    IMAGE[ImageType.PNG] = 'Portable Network Graphics Image (*.png)|*.png'
    IMAGE[ImageType.PPM] = 'Portable Pixmap image (*.ppm)|*.ppm'
    IMAGE[ImageType.TIFF] = 'Tagged Image File (*.tiff)|*.tiff'

    GEO = [''] * 10
    GEO[GeoType.BMP] = 'Bitmap image (*.bmp)|*.bmp'
    GEO[GeoType.CSV] = 'CSV Table (*.csv)|*.csv'
    GEO[GeoType.EPS] = 'Encapsulated PostScript (*.eps)|*.eps'
    GEO[GeoType.GIF] = 'GIF image (*.gif)|*.gif'
    GEO[GeoType.JPEG] = 'JPEG image (*.jpeg)|*.jpeg'
    GEO[GeoType.KMZ] = 'Google Earth (*.kmz)|*.kmz'
    GEO[GeoType.PDF] = 'Portable Document (*.pdf)|*.pdf'
    GEO[GeoType.PNG] = 'Portable Network Graphics Image (*.png)|*.png'
    GEO[GeoType.PPM] = 'Portable Pixmap image (*.ppm)|*.ppm'
    GEO[GeoType.TIFF] = 'Tagged Image File (*.tiff)|*.tiff'

    GMAP = [''] * 1
    GMAP[GMapType.HTML] = 'HTML Document (*.html)|*.html'

    TRACK = [''] * 1
    TRACK[TrackType.GPX] = 'GPX track (*.gpx)|*.gpx'

    CONT = [''] * 1
    CONT[PlotType.CSV] = PLOT[PlotType.CSV]

    HEADER = APP_NAME
    VERSION = 9

    @staticmethod
    def __get_types(f_type):
        return [File.SAVE, File.PLOT, File.IMAGE,
                File.GEO, File.GMAP, File.TRACK, File.CONT][f_type]

    @staticmethod
    def get_type_ext(index, f_type=Types.PLOT):
        types = File.__get_types(f_type)
        f_filter = types[index]
        delimiter = f_filter.index('|*')
        return f_filter[delimiter + 2:]

    @staticmethod
    def get_type_filters(f_type=Types.PLOT):
        types = File.__get_types(f_type)
        filters = ''
        length = len(types)
        for i in range(length):
            filters += types[i]
            if i < length - 1:
                filters += '|'

        return filters

    @staticmethod
    def get_type_pretty(f_type):
        types = File.__get_types(f_type)
        pretty = ''
        length = len(types)
        for i in range(length):
            pretty += File.get_type_ext(i, f_type)
            if i < length - 2:
                pretty += ', '
            elif i < length - 1:
                pretty += ' or '

        return pretty

    @staticmethod
    def get_type_index(extension, f_type=Types.PLOT):
        exports = File.__get_types(f_type)
        for i in range(len(exports)):
            if extension == File.get_type_ext(i, f_type):
                return i

        return -1


class ScanInfo:
    start = None
    stop = None
    dwell = None
    nfft = None
    name = None
    gain = None
    lo = None
    calibration = None
    tuner = 0
    time = None
    timeFirst = None
    timeLast = None
    lat = None
    lon = None
    desc = ''

    def set_from_settings(self, settings):
        self.start = settings.start
        self.stop = settings.stop
        self.dwell = settings.dwell
        self.nfft = settings.nfft
        device = settings.devicesRtl[settings.indexRtl]
        if device.isDevice:
            self.name = device.name
        else:
            self.name = device.server + ":" + str(device.port)
        self.gain = device.gain
        self.lo = device.lo
        self.calibration = device.calibration
        self.tuner = device.tuner

    def set_to_settings(self, settings):
        settings.start = self.start
        settings.stop = self.stop
        settings.dwell = self.dwell
        settings.nfft = self.nfft


class Backups:
    PREFIX = 'rsba_'

    def __init__(self):
        self.homeDir = os.path.expanduser('~')
        self.homeDir = os.path.join(self.homeDir, '.rtlsdr_scanner')
        if not os.path.exists(self.homeDir):
            os.mkdir(self.homeDir)
        self.thread = None
        self.backup = None
        self.tempFd, self.tempFile = tempfile.mkstemp(prefix=self.PREFIX,
                                                      dir=self.homeDir)
        self.backups = self.__get()

    def __get(self):
        files = []
        backups = glob.glob(self.homeDir + '/' + self.PREFIX + '*')
        if self.tempFile in backups:
            backups.remove(self.tempFile)

        for backup in backups:
            fTime = datetime.datetime.utcfromtimestamp(os.path.getmtime(backup))
            fSize = os.path.getsize(backup)
            if fSize:
                files.append((backup, fTime, fSize))
            else:
                try:
                    os.remove(backup)
                except OSError:
                    pass

        files.sort()
        files.reverse()
        return files

    def __save(self, data):
        handle = open(self.tempFile, 'wb')
        dump(data, handle)
        handle.close()
        self.thread = None

    def set(self, backup):
        self.backup = backup

    def save(self, scanInfo, spectrum, location):
        if self.thread is None:
            data = scanInfo, spectrum, location
            self.thread = threading.Thread(target=self.__save, args=(data,),
                                           name='Backup')
            self.thread.start()

    def load(self, index):
        backup = self.backups[index][0]
        handle = open(backup, 'rb')
        data = load(handle)
        handle.close()

        return data

    def delete(self, index):
        backup = self.backups[index][0]
        os.remove(backup)
        self.backups = self.__get()

    def close(self):
        os.close(self.tempFd)
        os.remove(self.tempFile)


def run_file(runFile):
    if os.name == 'nt':
        os.startfile(runFile)
        return True
    elif sys.platform.startswith('darwin'):
        return not subprocess.call(('open', runFile))
    elif os.name == 'posix':
        subprocess.call(('xdg-open', runFile))
        return True


def open_plot(dirname, filename):
    pickle = True
    error = False
    dwell = 0.131
    nfft = 1024
    name = None
    gain = None
    lo = None
    calibration = None
    tuner = 0
    spectrum = OrderedDict()
    time = None
    lat = None
    lon = None
    desc = ''
    start = 0
    stop = 0
    location = OrderedDict()
    header = File.HEADER
    path = os.path.join(dirname, filename)
    if not os.path.exists(path):
        return None, None, None
    handle = open(path, 'rb')
    try:
        header = load(handle)
    except UnpicklingError:
        pickle = False
    except EOFError:
        pickle = False

    if pickle:
        try:
            _version = load(handle)
            start = load(handle)
            stop = load(handle)
            spectrum[1] = {}
            spectrum[1] = load(handle)
        except PickleError:
            error = True
    else:
        try:
            handle.seek(0)
            data = json.loads(handle.read())
            header = data[0]
            version = data[1]['Version']
            start = data[1]['Start']
            stop = data[1]['Stop']
            if version > 1:
                dwell = data[1]['Dwell']
                nfft = data[1]['Nfft']
            if version > 2:
                name = data[1]['Device']
                gain = data[1]['Gain']
                lo = data[1]['LO']
                calibration = data[1]['Calibration']
            if version > 4:
                tuner = data[1]['Tuner']
            if version > 5:
                time = data[1]['Time']
                lat = data[1]['Latitude']
                lon = data[1]['Longitude']
            if version < 7:
                spectrum[1] = {}
                for f, p in data[1]['Spectrum'].items():
                    spectrum[1][float(f)] = p
            else:
                for t, s in data[1]['Spectrum'].items():
                    spectrum[float(t)] = {}
                    for f, p in s.items():
                        spectrum[float(t)][float(f)] = p
            if version > 7:
                desc = data[1]['Description']
            if version > 8:
                location = {}
                for t, l in data[1]['Location'].items():
                    location[float(t)] = l

        except ValueError:
            error = True
        except KeyError:
            error = True

    handle.close()

    if error or header != File.HEADER:
        wx.MessageBox('Invalid or corrupted file', 'Warning',
                      wx.OK | wx.ICON_WARNING)
        return None, None, None

    scanInfo = ScanInfo()
    scanInfo.start = start
    scanInfo.stop = stop
    scanInfo.dwell = dwell
    scanInfo.nfft = nfft
    scanInfo.name = name
    scanInfo.gain = gain
    scanInfo.lo = lo
    scanInfo.calibration = calibration
    scanInfo.tuner = tuner
    scanInfo.time = time
    scanInfo.lat = lat
    scanInfo.lon = lon
    scanInfo.desc = desc
    spectrum = sort_spectrum(spectrum)
    return scanInfo, spectrum, location


def save_plot(filename, scanInfo, spectrum, location):
    data = [File.HEADER, {'Version': File.VERSION,
                          'Start': scanInfo.start,
                          'Stop': scanInfo.stop,
                          'Dwell': scanInfo.dwell,
                          'Nfft': scanInfo.nfft,
                          'Device': scanInfo.name,
                          'Gain': scanInfo.gain,
                          'LO': scanInfo.lo,
                          'Calibration': scanInfo.calibration,
                          'Tuner': scanInfo.tuner,
                          'Time': scanInfo.time,
                          'Latitude': scanInfo.lat,
                          'Longitude': scanInfo.lon,
                          'Description': scanInfo.desc,
                          'Spectrum': spectrum,
                          'Location': location}]

    handle = open(os.path.join(filename), 'wb')
    handle.write(bs(json.dumps(data, indent=4)))
    handle.close()


def export_plot(filename, exportType, spectrum):
    handle = open(filename, 'wb')
    if exportType == File.PlotType.CSV:
        export_csv(handle, spectrum)
    elif exportType == File.PlotType.GNUPLOT:
        export_plt(handle, spectrum)
    elif exportType == File.PlotType.FREEMAT:
        export_freemat(handle, spectrum)
    elif exportType == File.PlotType.WWB:
        export_wwb(handle, spectrum)
    handle.close()


def export_cont(handle, filename, spectrum):
    if handle is None and filename is not None:
        handle = open(filename, 'wb')
        export_csv(handle, None)
    else:
        export_csv(handle, spectrum, False)

    return handle


def export_image(filename, i_format, figure, settings):
    oldSize = figure.get_size_inches()
    oldDpi = figure.get_dpi()
    figure.set_size_inches((settings.exportWidth, settings.exportHeight))
    figure.set_dpi(settings.exportDpi)

    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    renderer = canvas.get_renderer()
    if matplotlib.__version__ >= '1.2':
        buf = renderer.buffer_rgba()
    else:
        buf = renderer.buffer_rgba(0, 0)
    size = canvas.get_width_height()
    image = Image.frombuffer('RGBA', size, buf, 'raw', 'RGBA', 0, 1)
    image = image.convert('RGB')
    ext = File.get_type_ext(i_format, File.Types.IMAGE)
    image.save(filename, format=ext[1::], dpi=(settings.exportDpi,
                                               settings.exportDpi))

    figure.set_size_inches(oldSize)
    figure.set_dpi(oldDpi)


def export_map(filename, exportType, bounds, image, xyz):
    if exportType == File.GeoType.KMZ:
        export_kmz(filename, bounds, image)
    elif exportType == File.GeoType.CSV:
        export_xyz(filename, xyz)
    else:
        export_map_image(filename, exportType, image)


def export_csv(handle, spectrum, header=True):
    if header:
        handle.write(bs("Time (UTC), Frequency (MHz),Level (dB/Hz)\n"))
    if spectrum is not None:
        for plot in spectrum.items():
            for freq, pwr in plot[1].items():
                handle.write(bs("{}, {}, {}\n".format(plot[0], freq, pwr)))


def export_plt(handle, spectrum):
    handle.write(bs('set title "RTLSDR Scan"\n'))
    handle.write(bs('set xlabel "Frequency (MHz)"\n'))
    handle.write(bs('set ylabel "Time"\n'))
    handle.write(bs('set zlabel "Level (dB/Hz)"\n'))
    handle.write(bs('set ydata time\n'))
    handle.write(bs('set timefmt "%s"\n'))
    handle.write(bs('set format y "%H:%M:%S"\n'))
    handle.write(bs('set pm3d\n'))
    handle.write(bs('set hidden3d\n'))
    handle.write(bs('set palette rgb 33,13,10\n'))
    handle.write(bs('splot "-" using 1:2:3 notitle with lines \n'))
    for plot in spectrum.items():
        handle.write(bs('\n'))
        for freq, pwr in plot[1].items():
            handle.write(bs("{} {} {}\n".format(freq, plot[0], pwr)))


def export_freemat(handle, spectrum):
    x, y, z = create_mesh(spectrum, False)
    write_numpy(handle, x, 'x')
    write_numpy(handle, y, 'y')
    write_numpy(handle, z, 'z')
    handle.write(bs('\n'))
    handle.write(bs('surf(x,y,z)\n'))
    handle.write(bs('view(3)\n'))
    handle.write(bs("set(gca, 'plotboxaspectratio', [3, 2, 1])\n"))
    handle.write(bs("title('RTLSDR Scan')\n"))
    handle.write(bs("xlabel('Frequency (MHz)')\n"))
    handle.write(bs("ylabel('Time')\n"))
    handle.write(bs("zlabel('Level (dB/Hz)')\n"))
    handle.write(bs("grid('on')\n"))


def export_wwb(handle, spectrum):
    fileUuid = uuid.uuid4()
    fileTime = datetime.datetime.utcfromtimestamp(min(spectrum))
    header = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<scan_data_source ver="0.0.0.1" id="{{{}}}" model="TODO" '
              'name="{}" date="{}" time="{}" color="#00ff00">\n'
              '\t<data_sets count="{}" '
              'no_data_value="-140">\n').format(fileUuid,
                                                APP_NAME,
                                                fileTime.strftime('%a %b %d %Y'),
                                                fileTime.strftime('%H:%M:%S'),
                                                len(spectrum))
    handle.write(bs(header))

    freqs = '\t\t<freq_set>\n'
    for freq in spectrum[min(spectrum)]:
        freqs += '\t\t\t<f>{}</f>\n'.format(freq * 1e3)
    freqs += '\t\t</freq_set>\n'
    handle.write(bs(freqs))

    i = 0
    for sweep in spectrum.items():
        dataTime = datetime.datetime.utcfromtimestamp(sweep[0])
        dataSet = ('\t\t<data_set index="{}" freq_units="KHz" ampl_units="dBm" '
                   'start_freq="{}" stop_freq="{}" step_freq="{}" '
                   'res_bandwidth="TODO" scale_factor="1" '
                   'date="{}" time="{}" '
                   'date_time="{}">\n').format(i,
                                               min(sweep[1]) * 1e3,
                                               max(sweep[1]) * 1e3,
                                               1.953125,
                                               dataTime.strftime('%a %b %d %Y'),
                                               dataTime.strftime('%H:%M:%S'),
                                               sweep[0])
        handle.write(bs(dataSet))
        i += 1

        values = ''
        for scan in sweep[1].items():
            values += '\t\t\t<v>{:.1f}</v>\n'.format(scan[1])
        handle.write(bs(values))

        handle.write(bs('\t\t</data_set>\n'))

    handle.write(bs('\t</data_sets>\n'))
    handle.write(bs('\t<markers/>\n'))
    handle.write(bs('</scan_data_source>\n'))


def export_kmz(filename, bounds, image):
    tempPath = tempfile.mkdtemp()

    name = os.path.splitext(os.path.basename(filename))[0]
    filePng = name + '.png'
    fileKml = name + '.kml'

    image.save('{}/{}'.format(tempPath, filePng))

    handle = open('{}/{}'.format(tempPath, fileKml), 'wb')

    s = '<?xml version="1.0" encoding="UTF-8"?>\n' \
        '<kml xmlns="http://www.opengis.net/kml/2.2" ' \
        'xmlns:gx="http://www.google.com/kml/ext/2.2" ' \
        'xmlns:kml="http://www.opengis.net/kml/2.2" ' \
        'xmlns:atom="http://www.w3.org/2005/Atom">\n' \
        '<GroundOverlay>\n' \
        '\t<name>{} - {}</name>\n'.format(APP_NAME, name) \
        + '\t<Icon>\n' \
        + '\t\t<href>files/{}</href>\n'.format(filePng) \
        + '\t\t<viewBoundScale>0.75</viewBoundScale>\n' \
        + '\t</Icon>\n' \
        + '\t<LatLonBox>\n' \
        + '\t\t<north>{}</north>\n'.format(bounds[3]) \
        + '\t\t<south>{}</south>\n'.format(bounds[2]) \
        + '\t\t<east>{}</east>\n'.format(bounds[1]) \
        + '\t\t<west>{}</west>\n'.format(bounds[0]) \
        + '\t</LatLonBox>\n' \
        + '</GroundOverlay>\n' \
        + '</kml>\n'

    handle.write(bs(s))

    kmz = zipfile.ZipFile(filename, 'w')
    kmz.write('{}/{}'.format(tempPath, fileKml),
              '/{}'.format(fileKml))
    kmz.write('{}/{}'.format(tempPath, filePng),
              '/files/{}'.format(filePng))
    kmz.close()

    os.remove('{}/{}'.format(tempPath, filePng))
    os.remove('{}/{}'.format(tempPath, fileKml))
    os.rmdir(tempPath)


def export_xyz(filename, xyz):
    handle = open(filename, 'wb')
    handle.write(bs('x, y, Level (dB/Hz)\n'))
    for i in range(len(xyz[0])):
        handle.write(bs("{}, {}, {}\n".format(xyz[0][i], xyz[1][i], xyz[2][i])))
    handle.close()


def export_map_image(filename, exportType, image):
    ext = File.get_type_ext(exportType, File.Types.IMAGE)
    image.save(filename, format=ext[1::])


def export_gpx(filename, locations, name):
    handle = open(filename, 'wb')

    header = ('<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
              '<gpx xmlns="http://www.topografix.com/GPX/1/1" creator="{}" version="1.1">\n'
              '\t<trk>\n'
              '\t\t<name>{}</name>\n'
              '\t\t<trkseg>\n').format(name, 'test name')
    handle.write(bs(header))

    for location in sorted(locations.items()):
        timeStamp = format_iso_time(location[0])
        lat = location[1][0]
        lon = location[1][1]
        alt = location[1][2]
        point = ('\t\t\t<trkpt lat="{}" lon="{}">\n'
                 '\t\t\t\t<ele>{}</ele>\n'
                 '\t\t\t\t<time>{}</time>\n'
                 '\t\t\t</trkpt>\n').format(lat, lon, alt, timeStamp)
        handle.write(bs(point))

    footer = ('\t\t</trkseg>\n'
              '\t</trk>\n'
              '</gpx>\n')
    handle.write(bs(footer))
    handle.close()


def write_numpy(handle, array, name):
    handle.write(bs('{}=[\n'.format(name)))
    for i in array:
        for j in i:
            handle.write(bs('{} '.format(j)))
        handle.write(bs(';\n'))
    handle.write(bs(']\n'))


def extension_add(fileName, index, fileType):
    _name, extCurrent = os.path.splitext(fileName)
    ext = File.get_type_ext(index, fileType)
    if extCurrent != ext:
        return fileName + ext

    return fileName


if __name__ == '__main__':
    print('Please run rtlsdr_scan.py')
    exit(1)
