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

import math as m
from itertools import product
from numpy import inf, array, zeros, unique, pi, log, sqrt, where, stack, atleast_2d, squeeze, all
from numpy.random import normal, uniform
from scipy.stats import gamma as gm


class Prior:
    def __init__(self):
        raise NotImplementedError

    def logpdf(self, v):
        raise NotImplementedError

    def rvs(self, size):
        raise NotImplementedError


class DefaultPrior(Prior):
    def logpdf(self, v: float):
        return 0

    def rvs(self, size):
        return zeros(size)


class NormalPrior(Prior):
    def __init__(self, mean: float, std: float):
        self.mean = float(mean)
        self.std = float(std)
        self._f1 = 1 / m.sqrt(2*pi*std**2)
        self._lf1 = m.log(self._f1)
        self._f2 = 1 / (2*std**2)

    def logpdf(self, x):
        return self._lf1 -self._f2*(x-self.mean)**2

    def rvs(self, size=1):
        return normal(self.mean, self.std, size)


class UniformPrior(Prior):
    def __init__(self, a: float, b: float):
        self.a, self.b = a, b
        self.lnc = m.log(b-a)

    def logpdf(self, v):
        return where((self.a < v) & (v < self.b), self.lnc, -inf)

    def rvs(self, size=1):
        return uniform(self.a, self.b, size)


class JeffreysPrior(Prior):
    def __init__(self, x0: float, x1: float):
        self.x0 = x0
        self.x1 = x1
        self._f = log(x1 / x0)

    def pdf(self, x):
        return where((x > self.x0) & (x < self.x1), 1. / (x * self._f), -inf)

    def logpdf(self, x):
        return where((x > self.x0) & (x < self.x1), -log(x * self._f), -inf)

    def rvs(self, size=1):
        return exp(uniform(log(self.x0), log(self.x1), size))

class LogLogisticPrior(Prior):
    def __init__(self, a, b):
        self.a, self.b = a, b

    def logpdf(self, v):
        if not 1e-3 < v < 1.:
            return -inf
        else:
            a,b = self.a, self.b
            return m.log((b / a) * (v / a) ** (b - 1.) / (1. + (v / a) ** b) ** 2)

    def rvs(self, size=1):
        return uniform(1e-3, 1.0, size)


class GammaPrior(Prior):
    def __init__(self, a):
        self.a = a
        self.A = -m.lgamma(a)

    def logpdf(self, x):
        return self.A + (self.a - 1.) * log(x) - x

    def rvs(self, size):
        return gm(self.a).rvs(size)


class Parameter:
    def __init__(self, name, description='', unit='', prior=None, bounds=(-inf, inf), **kwargs):
        self.name = name
        self.description = description
        self.unit = unit
        self.prior = prior or DefaultPrior()
        self.bounds = bounds
        self.pid = -1
        self.scope = kwargs.get('scope', 'global')
        assert self.scope in ['global', 'local', 'passband']

    def __str__(self):
        return self.name

    def __repr__(self):
        return "{:3d} |{:1s}| {:10s} [{:4.2f} .. {:4.2f}]".format(self.pid, self.scope[0].upper(), self.name,
                                                                  self.bounds[0], self.bounds[1])

    def truncated_lnprior(self, v):
        if self.bounds[0] < v < self.bounds[1]:
            return self.prior.logpdf(v)
        else:
            return -inf

    def lnprior(self, v):
        return self.prior.logpdf(v)

    def rvs(self, size):
        return self.prior.rvs(size)


class GParameter(Parameter):
    def __init__(self, name, description='', unit='', prior=None, bounds=(-inf, inf), **kwargs):
        super().__init__(name, description, unit, prior, bounds, scope='global', **kwargs)


class LParameter(Parameter):
    def __init__(self, name, description='', unit='', prior=None, bounds=(-inf, inf), **kwargs):
        super().__init__(name, description, unit, prior, bounds, scope='local', **kwargs)


class PParameter(Parameter):
    def __init__(self, name, description='', unit='', prior=None, bounds=(-inf, inf), **kwargs):
        super().__init__(name, description, unit, prior, bounds, scope='passband', **kwargs)


class GParameterBlock:
    def __init__(self, name, start, stop):
        self.name = name
        self.start = start
        self.stop = stop
        self.slice = slice(self.start, self.stop)

    def __repr__(self):
        return "GParameterBlock('{}', {}, {})".format(self.name, self.start, self.stop)


class PParameterBlock(GParameterBlock):
    def __init__(self, name, start, stop, isize, npb):
        assert (stop-start) // isize == npb, "The number of parameter sets != npb"
        assert (stop-start) % isize == 0
        super(PParameterBlock, self).__init__(name, start, stop)
        self.isize = isize
        self.nelem = nelem = (stop-start) // isize
        self.slice = slice(self.start, self.stop)
        self.slices = [slice(self.start+isize*i, self.start+isize*(i+1)) for i in range(nelem)]

    def __repr__(self):
        return "<PParameterBlock('{}', {}, {}, {})".format(self.name, self.start, self.stop, self.isize)


class LParameterBlock(GParameterBlock):
    def __init__(self, name, start, stop, isize, nlc):
        assert (stop-start) // isize == nlc, "The number of parameter sets != nlc "
        assert (stop-start) % isize == 0
        super(LParameterBlock, self).__init__(name, start, stop)
        self.isize = isize
        self.nelem = nelem = (stop-start) // isize
        self.slice = slice(self.start, self.stop)
        self.slices = [slice(self.start+isize*i, self.start+isize*(i+1)) for i in range(nelem)]

    def __repr__(self):
        return "<LParameterBlock('{}', {}, {}, {})".format(self.name, self.start, self.stop, self.isize)


class ParameterSet(list):
    def __init__(self, *args):
        super().__init__(*args)
        self.blocks = []
        self.bounds = None
        self.frozen = False

    def add_global_block(self, name, pars):
        start = len(self)
        stop = start + len(pars)
        self.blocks.append(GParameterBlock(name, start, stop))
        self.extend(pars)

    def add_passband_block(self, name, isize, npb, pars):
        start = len(self)
        stop = start + len(pars)
        self.blocks.append(PParameterBlock(name, start, stop, isize, npb))
        self.extend(pars)

    def add_lightcurve_block(self, name, isize, nlc, pars):
        start = len(self)
        stop = start + len(pars)
        self.blocks.append(LParameterBlock(name, start, stop, isize, nlc))
        self.extend(pars)

    def append(self, *args):
        if not self.frozen:
            super().append(*args)
        else:
            raise ValueError('Trying to append to a frozen ParameterSet')

    def extend(self, *args):
        if not self.frozen:
            super().extend(*args)
        else:
            raise ValueError('Trying to extend a frozen ParameterSet')

    def _update_indices(self):
        if not self.frozen:
            self.bounds = array([p.bounds for p in self])
            self.lbounds = self.bounds[:, 0]
            self.ubounds = self.bounds[:, 1]
            for i, p in enumerate(self):
                p.pid = i
        else:
            raise ValueError('Trying to update a frozen ParameterSet')

    def lnprior(self, pv):
        pv = atleast_2d(pv)
        lnp = zeros(pv.shape[0])
        m = all(pv > self.bounds[:, 0], 1) & all(pv < self.bounds[:, 1], 1)
        for i, p in enumerate(self):
            lnp += p.lnprior(pv[:, i])
        return squeeze(where(m, lnp, -inf))

    def freeze(self):
        self._update_indices()
        self.frozen = True

    def thaw(self):
        self.frozen = False

    def validate(self):
        # General tests
        # -------------
        if not all(pd.Categorical(self.names).value_counts() == 1):
            raise ValueError('Duplicate parameter names are not allowed')

        # Validate global parameters
        # --------------------------

        # Validate the passband-dependent parameters
        # ------------------------------------------
        pnames = self.passband_parameters.names

        if not all(['_' in name for name in pnames]):
            raise ValueError('Passband-dependent parameters must be named as parameter_passband')

        pars = unique(list(n.split('_')[0] for n in pnames))
        pbs = unique(list(n.split('_')[1] for n in pnames))

        if not len(self.passband_parameters) == len(pars) * len(pbs):
            raise ValueError('Passband-dependent parameters must exist for all passbands')

        if not all(['{}_{}'.format(pr, pb) in pnames for pr, pb in product(pars, pbs)]):
            raise ValueError('Passband-dependent parameters must be named as parameter_passband')

        # Validate the per-light-curve parameters
        # ---------------------------------------



    def find_pid(self, name):
        for p in self:
            if name == p.name:
                return p.pid
        raise KeyError('Could not find parameter {}'.format(name))


    def sample_from_prior(self, size=1):
        return stack([p.rvs(size) for p in self.priors], 1)


    @property
    def names(self):
        return [p.name for p in self]

    @property
    def units(self):
        return [p.unit for p in self]

    @property
    def descriptions(self):
        return [p.description for p in self]

    @property
    def priors(self):
        return [p.prior for p in self]

    @property
    def scopes(self):
        return [p.scope for p in self]

    @property
    def global_parameters(self):
        return ParameterSet([p for p in self if p.scope == 'global'])

    @property
    def local_parameters(self):
        return ParameterSet([p for p in self if p.scope == 'local'])

    @property
    def passband_parameters(self):
        return ParameterSet([p for p in self if p.scope == 'passband'])