import pdb
import logging

import numpy as np
import pandas as pd

import sandy
from .basecov import BaseCov

__author__ = "Luca Fiorito"
__all__ = [
        "XsCov",
        ]

class XsCov(BaseCov):
    """Dataframe to contain cross section/nubar covariance matrices.
    Covariances can be stored for:
        
        - individual reactions,
        - cross reactions,
        - cross isotopes,
        - cross sections vs nubar

    **Index**:
        
        - MAT : (`int`) MAT number to identify the isotope
        - MT : (`int`) MT number to identify the reaction
        - E : (`float`) energy of the incident particle

    **Columns**:
        
        - MAT : (`int`) MAT number to identify the isotope
        - MT : (`int`) MT number to identify the reaction
        - E : (`float`) energy of the incident particle
    
    **Values**: matrix coefficients
    
    Methods
    -------
    from_endf6
        extract global cross section/nubar covariance matrix from 
        `sandy.formats.endf6.Endf6` instance
    from_errorr
        extract global cross section/nubar covariance matrix from 
        `sandy.formats.errorr.Errorr` instance  
        of `sandy.formats.utils.EnergyCov` instances
    get_samples
        extract perturbations from global cross section/nubar covariance matrix
    get_section
        extract section of global cross section/nubar covariance matrix as a 
        `sandy.formats.utils.EnergyCov` instance
    """

    labels = ["MAT", "MT", "E"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, dtype=float, **kwargs)
        index = self.index
        columns = self.columns
        self.index = index.set_levels([index.levels[0].astype(int), index.levels[1].astype(int), index.levels[2].astype(float)])
        self.columns = columns.set_levels([columns.levels[0].astype(int), columns.levels[1].astype(int), columns.levels[2].astype(float)])
        self.index.names = self.labels
        self.columns.names = self.labels

    def get_samples(self, nsmp, eig=0, seed=None):
        cov = self.to_matrix()
        frame = pd.DataFrame(cov.sampling(nsmp, seed=seed) + 1, index=self.index, columns=range(1,nsmp+1))
        frame.columns.name = 'SMP'
        if eig > 0 and nsmp > 1:
            eigs = cov.eig()[0]
            idxs = np.abs(eigs).argsort()[::-1]
            dim = min(len(eigs), eig)
            eigs_smp = sandy.formats.utils.Cov(np.cov(frame.values)).eig()[0]
            idxs_smp = np.abs(eigs_smp).argsort()[::-1]
            print("MF[31,33] eigenvalues:\n{:^10}{:^10}{:^10}".format("EVAL", "SAMPLES","DIFF %"))
            diff = sandy.functions.div0(eigs[idxs]-eigs_smp[idxs_smp], eigs[idxs], value=np.NaN)*100.
            E = ["{:^10.2E}{:^10.2E}{:^10.1F}".format(a,b,c) for a,b,c in zip(eigs[idxs][:dim], eigs_smp[idxs_smp][:dim], diff[:dim])]
            print("\n".join(E))
        return frame
    
    def get_section(self, mat, mt, mat1, mt1):
        """Extract section of the global covariance/correlation matrix.
        A section is defined by a unique combination of MAT/MT and MAT1/MT1 numbers.
        
        Parameters
        ----------
        mat : `int`
            MAT number for index
        mt : `int`
            MAT number for index
        mat1 : `int`
            MAT number for columns
        mt1 : `int`
            MT number for columns
        
        Returns
        -------
        `sandy.EnergyCov`
            section of the global covariance matrix
        """
        df = self.loc[(mat,mt), (mat1,mt1)]
        return sandy.EnergyCov(df)
    
    def _change_energy_grid(self, mat, mt, new_grid):
        df = self.index.to_frame(index=False)
        listdf = []
        for (mat_,mt_),edf in df.groupby(["MAT","MT"]):
            if mat_ == mat and mt_ == mt:
                edf = pd.MultiIndex.from_product([[mat],[mt],new_grid], names=["MAT","MT","E"]).to_frame(index=False)
            listdf.append(edf)
        df = pd.concat(listdf, ignore_index=True)
        index = df.set_index(['MAT', 'MT', "E"]).index
        cov = self.reindex(index=index, method="ffill").reindex(columns=index, method="ffill").fillna(0)
        return self.__class__(cov)

    @classmethod
    def from_endf6(cls, endf6):
        """Extract cross section/nubar covariance from `Endf6` instance.
        
        Parameters
        ----------
        endf6 : `sandy.formats.endf6.Endf6`
            `Endf6` instance containing covariance sections
        
        Returns
        -------
        `XsCov`
            global xs/nubar covariance matrix from ENDF6 file
        """
        tape = endf6.filter_by(listmf=[31,33])
        data = []
        # Loop MF/MT
        logging.debug("found {} covariance sections".format(len(tape)))
        for (mat,mf,mt), text in tape.TEXT.iteritems():
            X = tape.read_section(mat, mf, mt)
            # Loop subsections
            logging.debug("reading section MAT={}/MF={}/MT={}".format(mat, mf, mt))
            logging.debug("found {} subsections".format(len(X["SUB"])))
            for sub in X["SUB"].values():
                mat1 = sub['MAT1'] if sub['MAT1'] != 0 else mat
                mt1 = sub['MT1']
                logging.debug("\treading subsection MAT1={}/MT1={}".format(mat1, mt1))
                logging.debug("\tfound {} NI-type sub-subsection".format(len(sub["NI"])))
                covs = []
                # Loop NI-type covariances
                for i,nisec in sub["NI"].items():
                    logging.debug("\t\treconstruct covariance from NI-type section LB={}".format(nisec["LB"]))
                    if nisec["LB"] == 5:
                        foo = sandy.EnergyCov.from_lb5_asym if nisec["LS"] == 0 else sandy.EnergyCov.from_lb5_sym
                        cov = foo(nisec["EK"], nisec["FKK"])
                        covs.append(cov)
                    elif nisec["LB"] == 1:
                        cov = sandy.EnergyCov.from_lb1(nisec["EK"], nisec["FK"])
                        covs.append(cov)
                    elif nisec["LB"] == 2:
                        cov = sandy.EnergyCov.from_lb2(nisec["EK"], nisec["FK"])
                        covs.append(cov)
                    elif nisec["LB"] == 6:
                        cov = sandy.EnergyCov.from_lb6(nisec["EK"], nisec["EL"], nisec["FKL"])
                        covs.append(cov)
                    else:
                        logging.warn("skip LB={} covariance for [({}/{}), ({}/{})]".format(nisec["LB"], mat, mt, mat1, mt1))
                        continue
                if len(covs) == 0:
                    logging.debug("\tsubsection MAT1={}/MT1={} did not provide accetable covariances".format(mat1, mt1))
                    continue
                cov = sandy.EnergyCov.sum_covs(*covs)
                if cov.all().all():
                    logging.warn("\tempty covariance for [({}/{}), ({}/{})]".format(mat, mt, mat1, mt1))
                    continue
                data.append([(mat,mt), (mat1,mt1), cov])
        if not data:
            logging.warn("no xs covariance was found")
            return pd.DataFrame()
        return cls._from_list(data)

    @classmethod
    def from_errorr(cls, errorr):
        """Extract cross section/nubar covariance from `Errorr` instance.
        
        Parameters
        ----------
        errorr : `sandy.formats.endf6.Errorr`
            `Errorr` instance containing covariance sections
        
        Returns
        -------
        `XsCov`
            global xs/nubar covariance matrix from ERRORR file
        """
        tape = errorr.filter_by(listmf=[31,33])
        eg = errorr.energy_grid
        data = []
        # Loop MF/MT
        logging.debug("found {} covariance sections".format(len(tape)))
        for (mat,mf,mt), text in tape.TEXT.iteritems():
            X = tape.read_section(mat, mf, mt)
            # Loop subsections
            logging.debug("reading section MAT={}/MF={}/MT={}".format(mat, mf, mt))
            logging.debug("found {} subsections".format(len(X["RP"])))
            for mt1,cov in X["RP"].items():
                logging.debug("\treading subsection MAT1={}/MT1={}".format(mat, mt1))
                # add zero row and column at the end of the matrix (this must be done for ERRORR covariance matrices)
                cov = np.insert(cov, cov.shape[0], [0]*cov.shape[1], axis=0)
                cov = np.insert(cov, cov.shape[1], [0]*cov.shape[0], axis=1)
                cov = sandy.EnergyCov(cov, index=eg, columns=eg)
                data.append([(mat, mt), (mat, mt1), cov])
        if not data:
            logging.warn("no xs covariance was found")
            return pd.DataFrame()
        return cls._from_list(data)

    @classmethod
    def from_csv(cls, file, **kwargs):
        """
        Read multigroup xs covariance matrix from csv file.
        
        Parameters
        ----------
        file : `str`
            csv file
        **kwargs : keyword arguments, optional
            keyword arguments to pass to `pandas.DataFrame`
        
        Returns
        -------
        `XsCov`
            multi-group cross secrion covariance matrix object
        """
        df = pd.read_csv(file,
                         header=[0, 1, 2],
                         index_col=[0, 1, 2])
        return cls(df, **kwargs)

def from_endf6(endf):
    return XsCov.from_endf(endf)

def from_csv(file, **kwargs):
    return XsCov.from_csv(file, **kwargs)