#                             MAB-VLSI 
#
#                           Copyright 2018 
#   Regents of the University of California 
#                         All Rights Reserved
#
#                         
#  MAB-VLSI was developed by Shriram Kumar and Tushar Shah ai at
#  University of California, San Diego.
#
#  If your use of this software contributes to a published paper, we
#  request that you cite our paper that appears on our website 
#  http://vlsicad.ucsd.edu/MAB/MAB_v7.pdf
#
#  Permission to use, copy, and modify this software and its documentation is
#  granted only under the following terms and conditions.  Both the
#  above copyright notice and this permission notice must appear in all copies
#  of the software, derivative works or modified versions, and any portions
#  thereof, and both notices must appear in supporting documentation.
#
#  This software may be distributed (but not offered for sale or transferred
#  for compensation) to third parties, provided such third parties agree to
#  abide by the terms and conditions of this notice.
#
#  This software is distributed in the hope that it will be useful to the
#  community, but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  

import uuid
from utils import Sample
import logging
import numpy as np
from scipy.stats import gaussian_kde
import subprocess

class Sampler(object):
    """
    A sampler that can generate samples that can be used to update :py:class:`rewards.RewardModel`.
    
    ...
    
    Attributes
    __________
    attribute_names: string
        The names of attributes that are part of samples generated by the Sampler.
    metric_function: function
        The function that takes in the dictionary of attributes of a :py:class:`utils.Sample` and
        calculates the float metric value.
    valid_function: function
        The function that takes in the dictionary of attributes of a :py:class:`utils.Sample` and
        calculates the boolean validity of the sample.
    constants: dict
        The set of constants that are part of every sample.
    """
    def __init__(self, attribute_names, metric_function, valid_function, constants):
        self.attribute_names = attribute_names
        self.metric_function = metric_function
        self.valid_function = valid_function
        self.constants = constants

    def make_sample(self, attribute_values):
        """
        Generates a new sample.
        
        ...
        
        Parameters
        __________
        attribute_values: list
            The list of values to generate a sample from.
        """
        attributes = dict(zip(self.attribute_names, attribute_values))
        attributes.update(self.constants)
        return Sample(attributes, self.metric_function, self.valid_function)

    def get_samples(self, count):
        raise NotImplementedError('Get samples not implemented')

class SamplerSet:
    """
    Class to wrap a set of samplers and allow sampling the set for given batch sizes.

    ...
    
    Attributes
    __________
    samplers: list
        The set of samplers to generate the SamplerSet from.
    """
    def __init__(self, samplers):
        self.samplers = samplers

    def get_samples(self, sample_counts):
        """
        Get a batch of samples.
        
        ...
        
        Parameters
        __________
        sample_counts: int
            The number of samples to obtain.
        """
        return [s.get_samples(c) for s, c in zip(self.samplers, sample_counts)]

    def __len__(self):
        return len(self.samplers)

class GaussianSampler(Sampler): 
    """
    Implementation of the Sampler interface using a normal distribution to generate the samples.
    
    ...
    
    Parameters
    __________
    attributes_means: list
        The mean value to use per attribute. The order of attributes is the same as in attribute_names.
    attribute_stds: list
        The standard deviation to use per attribute. The order of attributes is the same as in attribute_names.
    """ 
    def __init__(self, attribute_names, metric_function, valid_function, constants, attribute_means, attribute_stds):
        super(GaussianSampler, self).__init__(attribute_names, metric_function, valid_function, constants)
        self.attribute_means = attribute_means
        self.attribute_stds = attribute_stds
        self.logger = logging.getLogger('Gaussian Sampler ' + str(id(self)))

    def get_samples(self, count):
        if count == 0:
            return []
        samples = np.random.multivariate_normal(self.attribute_means, np.diag(self.attribute_stds)**2, int(count))
        return map(self.make_sample, samples)

class KdeSampler(Sampler):
    """
    Implementation of the :py:class:`sampling.Sampler` interface using a KDE algorithm to generate samples given historical data.
    
    ...

    Parameters
    __________
    attribute_data: dict
        Dict containing the mapping from attribute name -> list of data. This data is used in the KDE model
        to generate new samples.
    """
    def __init__(self, attribute_names, metric_function, valid_function, constants, attribute_data):
        ''''''
        super(KdeSampler, self).__init__(attribute_names, metric_function, valid_function, constants)
        self.kde_estimates = dict([(name, gaussian_kde(data)) for name, data in attribute_data.items() if name not in constants])
        self.constants = constants
        self.logger = logging.getLogger('Gaussian Sampler ' + str(id(self)))

    def get_samples(self, count):
        data = []
        if count == 0:
            return data
        for name in self.attribute_names:
            if name in self.constants:
                data.append(count*[self.constants[name]])
            data.append(self.kde_estimates[name].resample(count).tolist()[0])
        return map(self.make_sample, zip(*data))

class ToolSampler(Sampler):
    """ 
    Implementation of the :py:class:`sampling.Sampler` interaface using real tool runs to generate the data. 
    
    ...

    Parameters
    __________
    noise_model: utils.NoiseModel
        The noise model used to add noise to arm parameters to obtain new samples. This procedure is called denoising. See [2]_ for more details.
    param_buffer: string
        The file to write denoised parameters to. The tool picks up these parameters and generates output data.
    sample_buffer: string
        The file that the tool writes output data to.
    script_path: string
        The path to the run script that comes packages with the tool. For more details see [3]_.
    params: list
        The mean parameters to supply to the ::py::class::`utils.NoiseModel`. Denoising is performed around these values

    ...

    References
    __________
    .. [2] Add the reference here.
    .. [3] Add another reference here.
    """
    def __init__(self, attribute_names, metric_function, valid_function, noise_model, constants, param_buffer, sample_buffer, script_path, params):
        super(ToolSampler, self).__init__(attribute_names, metric_function, valid_function, constants)
        self.params = params
        self.noise_model = noise_model
        self.param_buffer = param_buffer
        self.sample_buffer = sample_buffer
        self.logger = logging.getLogger('Tool Sampler ' + str(id(self)))
        self.script_path = script_path

    def get_samples(self, count):
        if count == 0:
            return []
        parameter_values = self.noise_model.add_noise(self.params, count)
        with open(self.param_buffer,"w+") as f:
            np.savetxt(f, parameter_values, delimiter = ',', fmt = '%1.5f')
        subprocess.call('source ' + self.script_path, shell = True)
        values = []
        with open(self.sample_buffer,"r") as f:
            header = f.readline()
            attributes = header.rstrip().split(",")
            if attributes != list(self.attribute_names):
                self.logger.warning('Attribute name mismatch encountered in buffer: trying to ignore')
            for line in f:
                values.append(map(float, line.split(',')))
        return map(self.make_sample,values)
