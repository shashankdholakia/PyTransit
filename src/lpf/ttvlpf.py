#  PyTransit: fast and easy exoplanet transit modelling in Python.
#  Copyright (C) 2010-2019  Hannu Parviainen
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.
from matplotlib.pyplot import subplots, setp
from numpy import pi, sign, cos, sqrt, sin, array, arccos, inf, round, int, s_, percentile, concatenate, median, mean, \
    arange

from numba import njit, prange
from pytransit.lpf.lpf import BaseLPF
from pytransit.transitmodel import TransitModel
from pytransit.param.parameter import ParameterSet, PParameter, GParameter
from pytransit.param.parameter import UniformPrior as U, NormalPrior as N, GammaPrior as GM
from pytransit.orbits_py import as_from_rhop

try:
    import seaborn as sb
    with_seaborn = True
except ImportError:
    with_seaborn = False

@njit("f8[:](f8[:], f8, f8, f8, f8[:], i8[:])", cache=False, parallel=False)
def z_circular_ttv(t, p, a, i, tc, tcid):
    cosph = cos(2*pi * (t - tc[tcid]) / p)
    z = sign(cosph) * a * sqrt(1.0 - cosph * cosph * sin(i) ** 2)
    return z


class TTVLPF(BaseLPF):
    """Log posterior function for TTV estimation.

    A log posterior function for TTV estimation. Each light curve represents a single transit, and
    is given a separate free transit centre parameter. The average orbital period and (one) transit
    zero epoch are assumed as known.

    Notes: The number of parameters can grow large with Kepler short-period planets.

    """
    def __init__(self, target: str, zero_epoch: float, period: float, tc_sigma: float, passbands: list,
                 times: list = None, fluxes: list = None, pbids: list = None, tm: TransitModel = None,
                 nsamples: int = 1, exptime: float = 0.020433598):
        self.zero_epoch = zero_epoch
        self.period = period
        self.tc_sigma = tc_sigma
        super().__init__(target, passbands, times, fluxes, pbids, tm, nsamples, exptime)

    def _init_p_orbit(self):
        """Orbit parameter initialisation for a TTV model.
        """
        porbit = [GParameter('rho', 'stellar_density', 'g/cm^3', U(0.1, 25.0), (0, inf)),
                  GParameter('b', 'impact_parameter', 'R_s', U(0.0, 1.0), (0, 1))]

        s = self.tc_sigma
        self.tnumber = round((array([t.mean() for t in self.times]) - self.zero_epoch) / self.period).astype(int)
        tcs = self.period * self.tnumber + self.zero_epoch
        for tc, tn in zip(tcs, self.tnumber):
            porbit.append(GParameter(f'tc_{tn:d}', f'transit_centre_{tn:d}', 'd', N(tc, s), (-inf, inf)))
        self.ps.add_global_block('orbit', porbit)
        self._start_tc = 2
        self._sl_tc = s_[self._start_tc:self._start_tc + self.nlc]

    def _compute_z(self, pv):
        a = as_from_rhop(pv[0], self.period)
        if a < 1.:
            return None
        else:
            i = arccos(pv[1] / a)
            tc = pv[self._sl_tc]
            return z_circular_ttv(self.timea, self.period, a, i, tc, self.lcida)

    def plot_light_curve(self, ax=None, figsize=None, time=False):
        fig, ax = (None, ax) if ax is not None else subplots(figsize=figsize)
        time = self.timea_orig if time else arange(self.timea_orig.size)
        ax.plot(time, concatenate(self.fluxes))
        ax.plot(time, concatenate(self.flux_model(self.de.minimum_location)))
        fig.tight_layout()
        return ax

    def posterior_period(self, burn: int = 0, thin: int = 1) -> float:
        df = self.posterior_samples(burn, thin, False)
        tccols = [c for c in df.columns if 'tc' in c]
        tcs = median(df[tccols], 0)
        return mean((tcs[1:] - tcs[0]) / (self.tnumber[1:] - self.tnumber[0]))

    def plot_ttvs(self, burn=0, thin=1, ax=None, figsize=None):
        fig, ax = (None, ax) if ax is not None else subplots(figsize=figsize)
        bwidth = 0.8
        df = self.posterior_samples(burn, thin)
        tccols = [c for c in df.columns if 'tc' in c]
        tcs = median(df[tccols], 0)
        period = mean((tcs[1:] - tcs[0]) / (self.tnumber[1:] - self.tnumber[0]))
        tc_linear = self.zero_epoch + self.tnumber * period
        p = 24*60*percentile(df[tccols] - tc_linear, [50, 16, 84, 0.5, 99.5], 0)
        ax.bar(self.tnumber, p[4,:]-p[3,:], bwidth, p[3,:], alpha=0.25, fc='b')
        ax.bar(self.tnumber, p[2,:]-p[1,:], bwidth, p[1,:], alpha=0.25, fc='b')
        [ax.plot((xx-0.47*bwidth, xx+0.47*bwidth), (pp[[0,0]]), 'k') for xx, pp in zip(self.tnumber,p.T)]
        setp(ax, ylabel='Transit center - linear prediction [min]', xlabel='Transit number')
        fig.tight_layout()
        if with_seaborn:
            sb.despine(ax=ax, offset=15)
        return ax