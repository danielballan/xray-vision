# ######################################################################
# Copyright (c) 2014, Brookhaven Science Associates, Brookhaven        #
# National Laboratory. All rights reserved.                            #
#                                                                      #
# Developed at the NSLS-II, Brookhaven National Laboratory             #
# Developed by Sameera K. Abeykoon, April 2014                         #
#                                                                      #
# Redistribution and use in source and binary forms, with or without   #
# modification, are permitted provided that the following conditions   #
# are met:                                                             #
#                                                                      #
# * Redistributions of source code must retain the above copyright     #
#   notice, this list of conditions and the following disclaimer.      #
#                                                                      #
# * Redistributions in binary form must reproduce the above copyright  #
#   notice this list of conditions and the following disclaimer in     #
#   the documentation and/or other materials provided with the         #
#   distribution.                                                      #
#                                                                      #
# * Neither the name of the Brookhaven Science Associates, Brookhaven  #
#   National Laboratory nor the names of its contributors may be used  #
#   to endorse or promote products derived from this software without  #
#   specific prior written permission.                                 #
#                                                                      #
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS  #
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT    #
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS    #
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE       #
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,           #
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES   #
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR   #
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)   #
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,  #
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OTHERWISE) ARISING   #
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE   #
# POSSIBILITY OF SUCH DAMAGE.                                          #
########################################################################

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import six
import sys
import logging

import numpy as np
from scipy import ndimage
import matplotlib
from matplotlib.widgets import Lasso
from matplotlib.patches import PathPatch
from matplotlib import path
from ..utils.mpl_helpers import ensure_ax_meth


logger = logging.getLogger(__name__)

"""This module will allow to draw a manual mask or region of interests(roi's)
for an image"""


class ManualMask(object):
    @ensure_ax_meth
    def __init__(self, ax, image, cmap='gray'):
        """
        Use a GUI to specify region(s) of interest.

        The user can draw as many regions as desired and, at any point
        during the process, access the results programatically using
        the attributes below.

        Note the following keyboard shortcuts:
        r - remove (cut holes)
        a - add (resume normal drawing)
        u - undo

        Parameters
        ----------
        ax : Axes, optional
        image : array
            backdrop shown under drawing
            This is used for visual purposes and to set the shape of the
            drawing canvas. Its content does not affect the output.
        cmap : str, optional
            'gray' by default

        Attributes
        ----------
        mask : boolean array
            all "postive" regions are True, negative False
        label_array : integer array
            each contiguous region is labeled with an integer
        label_by_stroke : integer array
            Each region drawn by the user is labeled with an integer.
            Even regions that are contiguous or overlapping are given
            unique labels if they were drawn separately. Where regions
            overlap, the last-drawn region takes precedence.
        sign : boolean
            While True, all drawings add to the region(s) of interest.
            While False, all drawing cuts holes in any regions of interest.

        Methods
        -------
        undo()
            Undo the last-drawn region.

        Example
        -------
        >>> m = ManualMask(my_img)
        >>> boolean_array = m.mask  # inside ROI(s) is True, outside False
        >>> label_array = m.label_array  # a unique number for each ROI
        """ 
        self.ax = ax
        self.canvas = ax.figure.canvas
        self.img_shape = image.shape
        self.ax.imshow(image, cmap)
        self.ax.set_title("(shortcuts: r - remove, a - add, z - undo)")
        y, x = np.mgrid[:image.shape[0], :image.shape[1]]
        self.points = np.transpose((x.ravel(), y.ravel()))
        self.canvas.mpl_connect('key_press_event', self.key_press_callback)
        self.cid = self.canvas.mpl_connect('button_press_event',
                                           self.on_press)
        self.sign = True  # draw postive masks, not holes
        self.regions = []
        self.holes = []
        self._undo_list = []  # references to regions and holes lists
        self._patches = []

    def on_press(self, event):
        if self.canvas.widgetlock.locked():
           return
        if event.inaxes is None:
           return
        self.lasso = Lasso(event.inaxes, (event.xdata, event.ydata),
                           self.call_back)
        # acquire a lock on the widget drawing
        self.canvas.widgetlock(self.lasso)

    def call_back(self, verts):
        p = path.Path(verts)
        self.patch = PathPatch(p, facecolor='g')
        self._patches.append(self.ax.add_patch(self.patch))

        self.canvas.draw_idle()
        self.canvas.widgetlock.release(self.lasso)

        is_contained = p.contains_points(self.points).reshape(self.mask.shape)
        if self.sign:
            self.regions.append(is_contained)
            self._undo_list.append(self.regions)
        else:
            self.holes.append(is_contained)
            self._undo_list.append(self.holes)

    def key_press_callback(self, event):
        # u - undo last stroke
        # r - remove (cut out)
        # a - add (cut out)
        if event.key == 'r':
            self.sign = False
        elif event.key == 'a':
            self.sign = True
        elif event.key == 'z':
            self.undo()

    @property
    def mask(self):
        return (flexible_or(self.regions, self.img_shape) 
                & ~flexible_or(self.holes, self.img_shape))
 
    @property
    def label_array(self):
        arr, num = ndimage.measurements.label(self.mask)
        return arr

    @property
    def label_by_stroke(self):
        # Each self.region has its own label. If regions overlap
        # the last-drawn region takes precedence.
        result = np.zeros(self.img_shape)
        for i, reg in enumerate(self.regions):
            result[reg] = i + 1
        result[flexible_or(self.holes, self.img_shape)] = 0

        return result

    def undo(self):
        "Remove the most recently drawn region."
        # First pop -> which list should I pop from
        # Second pop -> removing the array from that list
        self._undo_list.pop().pop()
        patch = self._patches.pop()
        patch.set_visible(False)
        self.ax.figure.canvas.draw()


def flexible_or(arrays, shape):
    """A 'logical or' that accepts 0, 1, or N input arrays.

    empty input -> zeros(shape)
    one array -> that array
    many arrays -> logical or

    Parameters
    ----------
    arrays : iterable of arrays
    shape: tuple
        sets shape of output if arrays is empty
    """
    len_arrays = len(arrays)
    if len_arrays == 0:
        return np.zeros(shape, dtype=bool)
    elif len_arrays == 1:
        return arrays[0]
    else:
        return np.logical_or(*arrays)
