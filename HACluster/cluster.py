# Hierarchical Agglomerative Cluster Analysis
#
# Copyright (C) 2013 Folgert Karsdorp
# Author: Folgert Karsdorp <fbkarsdorp@gmail.com>
# URL: <https://github.com/fbkarsdorp/HAC-python>
# For licence information, see LICENCE.TXT

from __future__ import division

import numpy
import copy
import argparse

from operator import itemgetter
from collections import defaultdict
from itertools import combinations, product

from api import AbstractClusterer
from dendrogram import Dendrogram
from distance import *
from linkage import *


class CooccurrenceMatrix(numpy.ndarray):
    """ Represents a co-occurrence matrix. """
    def __new__(cls, data, dtype=None):
        if not isinstance(data, CooccurrenceMatrix):
            data, rownames, colnames = CooccurrenceMatrix.convert(data)
        else:
            rownames, colnames = data.rownames, data.colnames
        obj = numpy.asarray(data).view(cls)
        obj.rownames = rownames
        obj.colnames = colnames
        return obj

    def __array_finialize__(self, obj):
        if obj is None: return
        self.rownames = getattr(obj, 'rownames', None)
        self.colnames = getattr(obj, 'colnames', None)
        
    def row(self, row):
        return self[self.rownames.get(row)]
        
    def col(self, col):
        return self[:,self.colnames.get(col)]
        
    def cell(self, row, col):
        return self[self.rownames.get(row), self.colnames.get(col)]

    @classmethod
    def convert(cls, data):
        matrix = numpy.zeros((len(set(k for k,v in data)),
                              len(set(v for k,v in data))))
        colnames, rownames = {}, {}
        for k,v in sorted(data):
            if k not in rownames:
                rownames[k] = len(rownames)
            if v not in colnames:
                colnames[v] = len(colnames)
            matrix[rownames[k],colnames[v]] += 1
        #rownames = [k for k,v in sorted(rownames.items(), key=itemgetter(1))]
        #colnames = [k for k,v in sorted(colnames.items(), key=itemgetter(1))]
        return matrix, rownames, colnames

    def tfidf(self):
        """
        Returns a matrix in which for all entries in the co-occurence matrix
        the 'term frequency-inverse document frequency' is calculated.
        """
        matrix = numpy.zeros(self.shape)
        # the number of words in a document
        words_per_doc = numpy.asarray(self.sum(axis=1), dtype=float)
        # the number of documents in which a word is attested.
        word_frequencies = numpy.asarray(numpy.sum(self > 0, axis=0), dtype=float)
        # calculate the term frequencies
        for i in xrange(self.shape[0]):
            tf = self[i] / words_per_doc[i] # array of tf's
            matrix[i] = tf * (numpy.log(self.shape[0] / word_frequencies))
        return matrix


class DistanceMatrix(numpy.ndarray):
    """
    Simple wrapper around numpy.ndarray, to provide some custom
    Distance Matrix functionality like plotting the distance matrix
    with matplotlib.
    """
    def __new__(cls, data, dist_metric=euclidean_distance, lower=True):
        if (not isinstance(data, (numpy.ndarray, DistanceMatrix))
            or len(data) != len(data[0])
            or not max(numpy.diag(data)) == 0):
            data = DistanceMatrix.convert_to_distmatrix(data, dist_metric, lower=lower)
        obj = numpy.asarray(data).view(cls)
        obj.distance_metric = dist_metric
        return obj

    def __array_finialize__(self, obj):
        if obj is None: return
        self.distance_metric = getattr(obj, 'distance_metric', None)
    
    def row(self, row):
        return self[self.rownames.get(row)]

    def col(self, col):
        return self[:,self.colnames.get(col)]

    def cell(self, row, col):
        return self[self.rownames.get(row), self.colnames.get(col)]  
        
    def rows(self):
        return [k for k,v in sorted(self.rownames.items(), key=itemgetter(1))]

    @classmethod
    def convert_to_distmatrix(cls, data, distance, lower=True):
        matrix = numpy.zeros((len(data), len(data)))
        for i,j in combinations(xrange(len(data)), 2):
            matrix[i][j] = distance(data[i], data[j])
            if lower == True:
                matrix[j][i] = matrix[i][j]
        # add a nan-diagonal, useful for further computations.
        numpy.fill_diagonal(matrix, numpy.nan)
        return matrix
            
    def diag_is_zero(self):
        """Check if the diagonal contains only distances of 0."""
        return max(numpy.diag(self)) == 0

    def remove(self, idx):
        """
        Delete a row and column with index IDX.
        WARNING this function is NOT destructive!
        """
        indices = range(len(self))
        indices.remove(idx)
        return self.take(indices, axis=0).take(indices, axis=1)

    def draw(self, save=False, format="pdf"):
        """Make a nice colorful plot of the distance matrix."""
        try:
            import pylab
        except ImportError:
            raise ImportError("Install pylab.")
        fig = pylab.figure()
        axmatrix = fig.add_axes([0.1,0.1,0.8,0.8])
        im = axmatrix.matshow(self, aspect='auto', origin='upper',
                              cmap=pylab.cm.YlGnBu)
        axcolor = fig.add_axes([0.91, 0.1, 0.02, 0.8])
        pylab.colorbar(im, cax=axcolor)
        fig.show()
        if save:
            fig.savefig('distance-matrix.%s' % (format,))

    def summary(self):
        """Return a small summary of the matrix."""
        print 'DistanceMatrix (n=%s)' % len(self)
        print 'Distance metric = %s' % self.distance_metric.__name__
        print self


class Clusterer(AbstractClusterer):
    """
    The Hierarchical Agglomerative Clusterer starts with each of the N vectors
    as singleton clusters. It then iteratively merges pairs of clusters which
    have the smallest distance according to function LINKAGE. This continues
    until there is only one cluster.
    """
    def __init__(self, data, dist_metric=euclidean_distance,
                 linkage = ward_link, num_clusters=1):
        self._num_clusters = num_clusters
        vector_ids = [[i] for i in range(len(data))]
        self._dendrogram = Dendrogram(vector_ids)
        self._dist_matrix = data
        self.linkage = linkage

    def smallest_distance(self, clusters):
        """
        Return the smallest distance in the distance matrix.
        The smallest distance depends on the possible connections in
        the distance matrix.
        
        @param clusters: an object of the class L{DistanceMatrix} holding the 
            clusters at a specific state in the clustering procedure.
        @type clusters: L{DistanceMatrix}
        @return: a tuple containing the smallest distance and the indexes of
            the clusters yielding the smallest distance.
        """
        i, j = numpy.unravel_index(numpy.nanargmin(clusters), clusters.shape)
        return clusters[i,j], i, j

    def cluster(self, verbose=0, sum_ess=False):
        """
        Cluster all clusters hierarchically until the level of
        num_clusters is obtained.
        
        @param verbose: how much output is produced during the clustering (0-2)
        @type verbose: C{int}
        
        @return: None, desctructive method. 
        """
        ## if sum_ess and self.linkage.__name__ != "ward_link":
        ##     raise ValueError(
        ##         "Summing for method other than Ward makes no sense...")
        clusters = copy.copy(self._dist_matrix)
        summed_ess = 0.0

        while len(clusters) > max(self._num_clusters, 1):
            if verbose >= 1:
                print 'k=%s' % len(clusters)
                if verbose == 2:
                    print clusters
            
            best, i, j = self.smallest_distance(clusters)
            # In Ward (1963) ess is summed at each iteration
            # in R's hclust and Python's hcluster and some text books it is not. 
            # Here it is optional...
            if sum_ess:
                summed_ess += best
            else:
                summed_ess = best
            clusters = self.update_distmatrix(i, j, clusters)
            self._dendrogram.merge(i,j)
            self._dendrogram._items[i].distance = summed_ess
            clusters = clusters.remove(j)

    def update_distmatrix(self, i, j, clusters):
        """
        Update the distance matrix using the specified linkage method so that
        it represents the correct distances to the newly formed cluster.
        """
        return self.linkage(clusters, i, j, self._dendrogram)

    def dendrogram(self):
        """Return the dendrogram object."""
        return self._dendrogram

    def num_clusters(self):
        return self._num_clusters

    def __repr__(self):
        return """<Hierarchical Agglomerative Clusterer(linkage method: %r,
                  n=%d clusters>""" % (self.linkage.__name__, self._num_clusters)


class VNClusterer(Clusterer):
    """
    Variability Neighbor Clustering Class. A subclass of the regular Clusterer
    where the order of clustering can be predetermined. In the normal clustering
    procedure, all clusters can be clustered with all other clusters. In this 
    class, the clusters that are allowed to be clustered follow a specific order.
    """
    def __init__(self, data, dist_metric=euclidean_distance,
                 linkage=ward_link, num_clusters=1):
        Clusterer.__init__(self, data, dist_metric, linkage, num_clusters)

    def iterate_clusters(self, clusters):
        for i in xrange(1, len(clusters)):
            yield i-1,i

    def smallest_distance(self, clusters):
        best = None
        for i, j in self.iterate_clusters(clusters):
            if best is None or clusters[i][j] <= best[0]:
                best = (clusters[i][j], i, j)
        return best

    def cluster(self, verbose=False):
        # we must sum the error sum of squares in order not to obtain
        # singleton clustering.
        Clusterer.cluster(self, verbose=verbose, sum_ess=True)


def demo():
    """Demo to show some basic functionality."""
    # input vector with two dimensions
    vectors = [[2,4], [0,1], [1,1], [3,2], [4,0], [2,2]]
    # compute the distance matrix on the basis of the vectors
    dist_matrix = DistanceMatrix(vectors, lambda u,v: numpy.sum((u-v)**2)/2)
    # plot the distance matrix
    dist_matrix.draw()
    # initialize a clusterer, with default linkage methode (Ward)
    clusterer = Clusterer(dist_matrix)
    # start the clustering procedure
    clusterer.cluster(verbose=2)
    # plot the result as a dendrogram
    clusterer.dendrogram().draw(title=clusterer.linkage.__name__)


if __name__ == '__main__':
    demo()


