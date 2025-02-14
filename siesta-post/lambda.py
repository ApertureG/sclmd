"""
Jing Tao L\"u, jtlu@nanotech.dtu.dk

=============================================================================
26Apr2018: Uses sisl and netCDF4
12Dec2013: this file works for new tbtrans developed by Nick
=============================================================================

Purpose:
========
Calculate Lambda function from output of Inelastica and TranSiesta.
What it needs:
    1. Dev.nc file from PHrun, 
    2. HSSigmaLR.nc from old tbtrans. The energy points should cover both 
	negative and positive energies. 
    3. *.TRANS and *.TEIG from tbtrans
What it outputs:
    avLambda.nc, including Lambda function, self-energy due to electrons,
    matrix in wideband approximation,average transmission,...
=============================================================================
Known problems:
1. When decomposing AL or AR, sometimes LA.eigh() does not converge. If that
    happens, try LA.eig()
2. Not ready for spin polarised claculation.
3. Memory problem for large calculation
=============================================================================
ToDo:

=============================================================================
"""
#!/usr/bin/env python

import glob
import sys
import time

import numpy as np
import numpy.linalg as LA
# new way to read in nc file
from netCDF4 import Dataset
from sclmd.functions import *
from sclmd.myio import ord2idx
Bohr2Ang = 0.5292

# ---------------------------------------------------------------------------
# class for storing data
# ---------------------------------------------------------------------------


class general:
    # parameters you can modify
    # hwcut      Lambda_{ij} is not calculated if abs(hw[i]-hw[j])>hwcut
    # doscut     cutoff for the eigenvalues of A,AL,AR, discard eigenvalues less
    #           than doscut*max value
    # mcut       similar cutoff for electron-phonon interaction matrix
    # gcut       similar cutoff for green's function Gr
    # recommend: set mcut and gcut to zero whenever possible
    # T          electronic temperature always zero

    # useFFT     using Fourier transform to calculate Lambda, always use this
    #           when possible

    # LL         calculate Lambda_{LL}
    # new        calculate Lambda_{equ} and Lambda_{nonequ},only work for useFFT=True

    doscut = 0.0
    mcut = 0.0
    gcut = 0.0
    T = 0.0

    mudefault = 0.0
    biasdefault = 0.0
    hwcutdefault = 0.005

    wbOnly = True
    debug = False
    LongOut = False
    checkFFT = False
    useFFT = True

    LL = False
    RR = False
    RL = False
    LR = False
    new = True


class HS:
    # Dummy to contain H, S and the Sigmas
    pass


class EPH:
    # Dummy to contain phonon and eph interaction matrix
    pass
# ---------------------------------------------------------------------------


# --------------------------------------------------------------------------
# user input parameters
print('Usage : python lamda.py  <PhononNetCDF> <Bias> <Ef> <phonon cutoff> <HSSigmaNetCDF>')
print('PhononNetCDF : Calculate MAMA using HSSigma and Heph NetCDF file')
print('Bias: The bias applied')
print('Ef: Position of Fermi level, muL=Ef+Bias, muR=Ef-Bias')
print('phonon cutoff: phonon energy beyond which the off-diagonal Lambda terms\
        are set to zero.')
print('HSSigmaNetCDF: HSSigmaMEAN.nc from TSrun')
args = sys.argv[1:]

try:
    general.PhononNetCDF = args[0]
except:
    print('Missing Heph input')
    sys.exit(1)

try:
    bias = float(args[1])
    mu = float(args[2])
    general.mu0 = mu
    general.muL = mu+bias/2.0
    general.muR = mu-bias/2.0
except:
    print('Missing bias, using default values')
    general.mu0 = general.mudefault
    general.muL = general.mudefault+general.biasdefault/2.0
    general.muR = general.mudefault-general.biasdefault/2.0

try:
    general.hwcut = float(args[3])
except:
    print('Missing hwcut,using default value')
    general.hwcut = general.hwcutdefault

try:
    general.hsfs = args[4]
except:
    print("Set HSSigmaMEAN.nc")
    general.hsfs = "../TSrun/HSSigmaMEAN.nc"

log = "hwcut="+str(general.hwcut)+", doscut="+str(general.doscut) +\
    ", mcut="+str(general.mcut)+",gcut="+str(general.gcut) +\
    ", debug="+str(general.debug)+", LongOut="+str(general.LongOut) +\
    ", useFFT="+str(general.useFFT)
print(log)
# --------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# main function
# ---------------------------------------------------------------------------


def main():
    muL = general.muL
    muR = general.muR
    mu0 = general.mu0
    hwcut = general.hwcut
    doscut = general.doscut
    mcut = general.mcut
    gcut = general.gcut
    T = general.T
    debug = general.debug
    LongOut = general.LongOut
    useFFT = general.useFFT

    LL = general.LL
    RR = general.RR
    RL = general.RL
    LR = general.LR
    new = general.new

    # read e-ph interaction, output from PHrun
    # spin down part
    ReadEph(mcut)

    # read dynamical matrix, eigen vectors
    dyn, nU, hw = ReadDynmat(general.PhononNetCDF)
    general.nU = nU

    # readin HSSigmaLR, output from tbtrans
    HSfs = glob.glob(general.hsfs)

    # ---------------------------------------------------------------------------------------
    # initialise the arrays
    # ---------------------------------------------------------------------------------------
    nm = len(EPH.hw)  # number of phonon modes
    nh = len(EPH.cM[0])  # size of electron basis

    # ---------------------------------------------------------------------------------------
    # read HSSigmas,calculate Lambda
    # ---------------------------------------------------------------------------------------
    print(HSfs)
    file = HSfs[0]
    print("reading ", file)
    readHS(file)

    print(HS.E)
    ave = HS.E

    ne = int(len(ave)/2)*2  # number of energy points

    if useFFT:
        nlam = ne
    else:
        nlam = ne

    print("calculating spectrum function")
    calcALR(doscut, gcut)

    print("calculating the wideband result")
    eta, xim, xip, zeta1, zeta2 = wbLambda(hwcut, 'wbLambda.nc', mu0)

    if general.wbOnly:
        print("done calculating wideband results!")
        sys.exit()

    print("calculating the full Lambda function")
    wl, LamLL, LamRR, LamLR, LamRL, LamEqu, LamNon, LamHNon =\
        calcLambda(useFFT, new, LL, RR, LR, RL, muL,
                   muR, hwcut, 'Lambda.nc', mu0)

    # ---------------------------------------------------------------------------------------
    # Construct the full Lambda and calculate phonon retarded self-energy from
    # electrons
    # ---------------------------------------------------------------------------------------
    # Maping according to symmetry
    # Lam^{ab}(w)=-Transpose(Lam^{ba}(-w))
    E = HS.E.copy()
    if useFFT:
        LamLL, LamRR, LamLR, LamRL = domapping(
            E, muL, muR, LamLL, LamRR, LamLR, LamRL)
    else:
        LamLL, LamRR, LamLR, LamRL = domapping(
            E, muL, muL, LamLL, LamRR, LamLR, LamRL)

    # from Lambda calculate the phonon retarded self-energy Pir
    # Pira=\Pi^r(w)-\Pi^a(w) = i2\pi(LamLL+LamRR+LamLR+LamRL)
    # We fourier transform Pira to time;zerofy the negative part;and fourier
    # transform back to get Pir
    Lam = LamLL+LamRR+LamLR+LamRL
    Pira = 2.0*np.pi*1.0j*Lam
    # Pira should be real at w=0
    # Pira[0]=(Pira[0]+np.conjugate(Pira[0]))*0.5

    nf = len(E)  # number of energy points
    npad = (nf/2)*2
    nfft = nf+npad  # add some 'buffer' zeros
    dt = 2*np.pi/nfft/(E[3]-E[2])  # time step of fft
    mfft = myfft(dt, nfft)  # initialise fft class
    nm = len(EPH.hw)  # number of phonons

    # pading, exponetial decay
    Pipad = np.zeros((npad, nm, nm), np.complex)
    for i in range(npad/2):
        Pipad[i] = np.conjugate(Pira[nf/2])*np.exp(-(i)/(npad/2/10.0))
        Pipad[npad-1-i] = Pira[nf/2]*np.exp(-(i+1)/(npad/2/10.0))
    Pirap = np.concatenate((Pira[0:nf/2], Pipad, Pira[nf/2:]), axis=0)

    Pir = np.zeros((nf, nm, nm), np.complex)
    for i in range(nm):
        for j in range(nm):
            tmp0 = Pirap[:, i, j]
            if(np.abs(tmp0).max() > 0.):
                # w->t
                tmp = mfft.iFourier1D(tmp0)
                # zerofy the negative time part
                tmp[(nf+npad)/2:] = 0j
                tmp[0] = tmp[0]*0.5
                # t->w
                tmp = mfft.Fourier1D(np.real(tmp))
                Pir[:, i, j] = np.concatenate(
                    (tmp[0:nf/2], tmp[nf/2+npad:]), axis=0)
    # new way of calculating Pir, excluding zero-bias renormalization
    Pir2 = 1.0j*np.pi*(LamEqu+LamNon-1.0j*LamHNon)

    # --------------------------------------------------------------------------------
    # OUTPUT TO FILES
    # --------------------------------------------------------------------------------
    # write the avLambda function
    # --------------------------------------------------------------------------------
    # put in normal order
    wl = reord(wl)
    LamLL = reord(LamLL)
    LamRR = reord(LamRR)
    LamLR = reord(LamLR)
    LamRL = reord(LamRL)
    LamEqu = reord(LamEqu)
    LamNon = reord(LamNon)
    LamHNon = reord(LamHNon)
    Pir = reord(Pir)
    Pir2 = reord(Pir2)
    AL = reord(AL)
    AR = reord(AR)
    TR = reord(TR)

    NCfile = Dataset('Lambda.nc', 'w', 'Created '+time.ctime(time.time()))
    NCfile.title = 'Output from MAMA.py'+log
    NCfile.createDimension('Nw', len(wl))
    NCfile.createDimension('NPh', len(EPH.hw))
    NCfile.createDimension('Nmu', 2)
    NCfile.createDimension('NT', 1)
    Write2NetCDFFile(NCfile, wl, 'wl', ('Nw',), units='eV')
    Write2NetCDFFile(NCfile, np.array(
        [muL, muR]), 'muLR', ('Nmu',), units='eV')
    Write2NetCDFFile(NCfile, np.array([T]), 'T', ('NT',), units='Kelvin')
    Write2NetCDFFile(NCfile, LamLL.real, 'ReLamLL',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamLL.imag, 'ImLamLL',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamRR.real, 'ReLamRR',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamRR.imag, 'ImLamRR',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamLR.real, 'ReLamLR',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamLR.imag, 'ImLamLR',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamRL.real, 'ReLamRL',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamRL.imag, 'ImLamRL',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamEqu.real, 'LamEqu',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamNon.real, 'ReLamNon',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamNon.imag, 'ImLamNon',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamHNon.real, 'ReLamHNon',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, LamHNon.imag, 'ImLamHNon',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, Pir.real, 'RePir', ('Nw', 'NPh',
                                                 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, Pir.imag, 'ImPir', ('Nw', 'NPh',
                                                 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, Pir2.real, 'RePir2', ('Nw', 'NPh',
                                                   'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, Pir2.imag, 'ImPir2', ('Nw', 'NPh',
                                                   'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, eta, 'eta', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, xim, 'xim', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, xip, 'xip', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, zeta1, 'zeta1', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, zeta2, 'zeta2', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, TR, 'trans', ('Nw',), units='None')
    Write2NetCDFFile(NCfile, AL, 'AL', ('Nw',), units='1/eV')
    Write2NetCDFFile(NCfile, AR, 'AR', ('Nw',), units='1/eV')
    NCfile.close()


def calcLambda(useFFT, new, LL, RR, LR, RL, muL, muR, hwcut, outfile, mu0=0):
    """
    calculate all the Lambdas and write to netcdf file
    useFFT: use fft or not
    new:    new way of calculating the Lambda
    LL:     calculate LL or not
    RR:     calculate RR or not
    LR:     calculate LR or not
    RL:    calculate RL or not
    muL:    fermi level of left electrode
    muR:    fermi level of right electrode
    hwcut:  cutoff for off-diagonal matrix element
    outfile:    output file
    """
    wl = HS.E.copy()
    dw = wl[1]-wl[0]
    if useFFT:
        print('FFT,calculating Lambda in energy range:', min(wl), max(wl))
        if LL is True:
            LamLL = np.array(LambdaFFT("L", "L", muL, muL, hwcut))
        else:
            LamLL = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
        if RR is True:
            LamRR = np.array(LambdaFFT("R", "R", muR, muR, hwcut))
        else:
            LamRR = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
        if LR or RL is True:
            LamLR = np.array(LambdaFFT("L", "R", muL, muR, hwcut))
            LamRL = np.array(LambdaFFT("R", "L", muR, muL, hwcut))
        else:
            LamLR = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
            LamRL = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
        if new is True:
            # calculating equilibrium,nonequilibrium,and Hilbert transform of the
            # nonequilibrium part
            LamEqu = EquLambdaFFT(hwcut, mu0)
            LamNon, LamHNon = NonequLambdaFFT(hwcut, muL, muR, mu0)
        else:
            LamEqu = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
            LamNon = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
            LamHNon = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)

    else:
        # do the energy integration without using FFT
        # maximu energy which is doable,outof this, set to zero
        maxw = min(muL, muR)-min(HS.E)
        # only for T=0
        if general.T != 0:
            print("WARNING: direct calculation works only T=0!!!")
            sys.exit()
        if LL is True:
            LamLL = np.array(
                [Lambda(w, "L", "L", muL, muL, dw, maxw, hwcut) for w in wl])
        else:
            LamLL = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
        if RR is True:
            LamRR = np.array(
                [Lambda(w, "R", "R", muR, muR, dw, maxw, hwcut) for w in wl])
        else:
            LamRR = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
        if LR or RL is True:
            LamLR = np.array(
                [Lambda(w, "L", "R", muL, muR, dw, maxw, hwcut) for w in wl])
            LamRL = np.array(
                [Lambda(w, "R", "L", muR, muL, dw, maxw, hwcut) for w in wl])
        else:
            LamLR = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
            LamRL = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
        LamEqu = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
        LamNon = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)
        LamHNon = np.zeros((len(wl), len(EPH.hw), len(EPH.hw)), np.complex)

    # -----------------------------------------------------------------------------------------
    # write the Lambda function
    # -----------------------------------------------------------------------------------------
    NCfile = Dataset(outfile, 'w', 'Created '+time.ctime(time.time()))
    NCfile.title = 'Output from MAMA.py'
    NCfile.createDimension('Nw', len(wl))
    NCfile.createDimension('NPh', len(EPH.hw))
    Write2NetCDFFile(NCfile, reord(wl), 'wl', ('Nw',), units='eV')
    Write2NetCDFFile(NCfile, reord(LamLL).real, 'ReLamLL',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamLL).imag, 'ImLamLL',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamLR).real, 'ReLamLR',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamLR).imag, 'ImLamLR',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamRL).real, 'ReLamRL',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamRL).imag, 'ImLamRL',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamRR).real, 'ReLamRR',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamRR).imag, 'ImLamRR',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamEqu).real, 'LamEqu',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamNon).real, 'ReLamNon',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamNon).imag, 'ImLamNon',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamHNon).real, 'ReLamHNon',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, reord(LamHNon).imag, 'ImLamHNon',
                     ('Nw', 'NPh', 'NPh',), units='0.06466 eV/amu/Angstrom**2')
    NCfile.close()

    return (wl, LamLL, LamRR, LamLR, LamRL, LamEqu, LamNon, LamHNon)

# -----------------------------------------------------------------------------


def domapping(E, fermiL, fermiR, LamLL, LamRR, LamLR, LamRL):
    """
    Using the symmetry properties of Lambda to get the 'negative' frequency part,
    which is not calculated directly:
        Lam^{ab}(w) = Dagger(Lam^{ab}(w))
        Lam^{ab}(w) = -Transpose(Lam^{ba}(-w))
    """
    nLamLL = LamLL.copy()
    nLamRR = LamRR.copy()
    nLamLR = LamLR.copy()
    nLamRL = LamRL.copy()
    for i in range(len(E)):
        if(E[i] < 0):
            ir = nearest(-E[i], E)
            nLamLL[i] = -np.transpose(LamLL[ir])
            nLamRR[i] = -np.transpose(LamRR[ir])
        if(E[i] < fermiL-fermiR):
            ir = nearest(-E[i], E)
            nLamLR[i] = -np.transpose(LamRL[ir])
        if(E[i] < fermiR-fermiL):
            ir = nearest(-E[i], E)
            nLamRL[i] = -np.transpose(LamLR[ir])
    return nLamLL, nLamRR, nLamLR, nLamRL
# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------


def calcALR(doscut, gcut):
    """
    calculate the electron properties, use the information stored in class HS:
        ALs     Tr[AL]
        ARs     Tr[AR]
        TRs     transmission
        WLs     important Eigenvectors of ALs
        WRs     important Eigenvectors of ARs

    In calculating Lambda, we use WLs and WRs to save time.
    Approximately, AL = WL^T * WL^*

    16sep11: save Gr also
    """

    S = HS.S
    H = HS.H

    n = len(H)
    print("No basis states in HSSigma: ", n)
    nm = len(EPH.hw)

    SigL = HS.Sig1
    SigR = HS.Sig2
    E = HS.E.copy()
    ne = len(E)

    HS.TRs = []
    HS.ALs = []
    HS.ARs = []
    HS.WLs = []
    HS.WRs = []
    HS.Ws = []
    HS.ReGvs = []
    HS.ReGcs = []

    for ii in range(len(E)):
        if general.LongOut:
            print("Using energy (eV): ", E[ii])
        SL = SigL[ii]
        SR = SigR[ii]
        GL = 1.0j*(SL-dagger(SL))
        GR = 1.0j*(SR-dagger(SR))
        G = LA.inv(E[ii]*S-H-SL-SR)
        Gd = dagger(G)

        # symmetric part of Re[Gr]
        [Gv, Gc] = cutM((G.real+np.transpose(G.real))/2, gcut)
        #decompose and save
        HS.ReGvs.append(Gv)
        HS.ReGcs.append(Gc)

        AL = mm(G, GL, Gd)
        AR = mm(G, GR, Gd)
        TR = np.trace(mm(AL, GR))

        WL = cutA(AL, doscut)
        WR = cutA(AR, doscut)
        W = cutA(AL+AR, doscut)

        HS.TRs.append(TR.real)
        HS.ALs.append(np.trace(AL).real)
        HS.ARs.append(np.trace(AR).real)
        HS.WLs.append(WL)
        HS.WRs.append(WR)
        HS.Ws.append(W)

    HS.TRs = np.array(HS.TRs)
    HS.ALs = np.array(HS.ALs)
    HS.ARs = np.array(HS.ARs)


def cutA(AL, doscut):
    """
    Eigenvalue decomposition of matrix AL

    Returns a matrix, which approximates AL as:
    AL \approx WL^T.WL^*
    """

    n = len(AL)
    # known prlblem: sometimes LA.eigh does not converge.
    try:
        tmpevL, tmpUL = LA.eigh(AL)
    except:
        tmpevL, tmpUL = LA.eig(AL)
    tmpUL = np.transpose(tmpUL)
    evL, UL = ev_sort(tmpevL, tmpUL)

    # check the eigenvalues and eigenvectors are allright
    tevm = np.zeros((len(evL), len(evL)), np.float)
    for i in range(len(evL)):
        tevm[i, i] = evL[i]
    rAL = mm(np.transpose(UL), tevm, np.conjugate(UL))
    # maxd=max(max(map(abs,rAL-AL)))
    maxd = np.abs(rAL-AL).max()
    if(maxd > 10**-8):
        print("something with the LA.eigh")
        print('max difference:', maxd)
        sys.exit()

    doscutL = evL.max()*doscut
    if general.LongOut:
        print("max evL, doscutL:", evL.max(), doscutL)

    nL = 0
    for e in evL:
        if e > doscutL:
            nL = nL+1
    if nL == 0:
        print("WARNING: no ev < doscut in 2: putting nL=1")
        nL = 1
    # print "Found ",nL," eigenvalues > doscut for AL"
    # print evL[0:nL]

    WL = np.zeros((nL, n), np.complex)
    for i in range(nL):
        WL[i, :] = np.sqrt(evL[i])*UL[i, :]
    return(WL)


def cutM(AL, doscut):
    """
    The eigenvalue of AL could be negative!!!

    Eigenvalue decomposition of matrix AL
    Returns a matrix, which approximates AL as:
    AL \approx WL^T*eL*WL^*
    """

    n = len(AL)
    tmpevL, tmpUL = LA.eigh(AL)
    tmpUL = np.transpose(tmpUL)
    evL, UL = ev_sort(tmpevL, tmpUL)

    # check the eigenvalues and eigenvectors are allright
    tevm = np.zeros((len(evL), len(evL)), np.float)
    for i in range(len(evL)):
        tevm[i, i] = evL[i]
    rAL = mm(np.transpose(UL), tevm, np.conjugate(UL))
    maxd = np.abs(rAL-AL).max()
    if(maxd > 10**-8):
        print("something with the LA.eigh")
        print('max difference:', maxd)
        sys.exit()

    doscutL = abs(evL).max()*doscut
    if general.LongOut:
        print("cutM: max evL, cutL:", evL.max(), doscutL)

    nL = 0
    WL = []
    eL = []
    for i in range(len(evL)):
        if abs(evL[i]) >= doscutL:
            nL = nL+1
            WL.append(UL[i, :])
            eL.append(evL[i])
    if nL == 0:
        print("WARNING: no ev < doscut in 2: putting nL=2")
        nL = 2
        WL.append(UL[0, :])
        WL.append(UL[1, :])
        eL.append(evL[0])
        eL.append(evL[1])
    if general.LongOut:
        print("Found ", nL, " eigenvalues > doscut for AL")
    return([np.array(eL), np.array(WL)])


def calcMAMA(w1, w2, a, b, hwcut):
    """
    Calculate MAMA by diagonizing the matrix A
    w1  energy of Aa
    w2  energy of Ab
    a,b L or R
    hwcut   cutoff of the off-diagonal matrix elements
    """
    if general.LongOut:
        print("--------------------------------------------------------\n")
        print("calcMAMA: Calculate MAMA by diagonizing the matrix A\n")
    spin = 2  # electron spin degeneracy
    E = HS.E.copy()
    id1 = nearest(w1, E)
    id2 = nearest(w2, E)
    if general.LongOut:
        print(("w1= %f, w2=%f \n" % (w1, w2)))
        print(("using energy w1= %f, w2=%f \n" % (E[id1], E[id2])))
        print(("a= %s, b= %s\n" % (a, b)))

    if a is "L":
        Wa = HS.WLs[id1]
    elif a is "R":
        Wa = HS.WRs[id1]
    else:
        print("a has to be L or R")
        sys.exit()
    if b is "L":
        Wb = HS.WLs[id2]
    elif b is "R":
        Wb = HS.WRs[id2]
    else:
        print("b has to be L or R")
        sys.exit()

    hw = EPH.hw
    cM = EPH.cM
    cV = EPH.cV
    nm = len(hw)

    MAaMAb = np.zeros((nm, nm), np.complex)

    ########################################################################
    #   W_a is the diagonal matrix, whose diagonal matrix element are the
    #   eigenvalues give by LA.Heigenvectors()
    #   Q_a is the matrix give by LA.Heigenvectors(),
    #   the n-th row of which corresponds to the n-th eigenvectors.
    #
    #    (MAaMAb)ij=Tr[(M_i)Aa(M_j)Ab]
    #   =Tr[(M_i)(Q_a^T)(W_a)(Q_a^*)(M_j)(Q_b^T)(W_b)(Q_b^*)]
    #   =Tr[(M_i)(P_a^T)(P_a^*)(M_j)(P_b^T)(P_b^*)]
    #   =Tr[(P_b^*)(M_i)(P_a^T)(P_a^*)(M_j)(P_b^T)]
    #
    #
    ########################################################################
    i = 0
    for ihw1 in range(nm):
        cM1 = cM[ihw1]
        cV1 = cV[ihw1]
        M1ab = mm(mm(np.conjugate(Wb), np.multiply(cM1.T, cV1)),
                  mm(np.conjugate(cM1), np.transpose(Wa))).flatten()

        # only calculate the off triangular part
        for ihw2 in range(ihw1+1):
            if abs(hw[ihw1]-hw[ihw2]) > hwcut:
                if general.LongOut:
                    print('skip: hw[i]-hw[j]=', abs(hw[ihw1]-hw[ihw2]))
                continue
            if hw[ihw1] < 0 or hw[ihw2] < 0:
                if general.LongOut:
                    print('skip: negative frequency!')
                continue
            cM2 = cM[ihw2]
            cV2 = cV[ihw2]

            # M2=mm(np.multiply(wm.T,vm),np.conjugate(wm))
            # M2ab=mm(Wb,np.transpose(M2),dagger(Wa)).flatten()
            # M2ab=mm(Wb,np.transpose(mm(np.multiply(cM2.T,cV2),np.conjugate(cM2))),dagger(Wa)).flatten()
            M2ab = mm(mm(Wb, dagger(cM2)), mm(np.transpose(
                np.multiply(cM2.T, cV2)), dagger(Wa))).flatten()

            # print ihw1,ihw2,len(M1ab),len(M2ab)
            MAaMAb[ihw1, ihw2] = mm(M1ab, M2ab)

            i = i+1
            # print "Modes: ", ihw1,ihw2,100*i/(nm*nm),"% done"

    MAaMAb = herm(MAaMAb)  # construct the upper triangular part
    if general.LongOut:
        print("Leaving calcMAMA:\n")
        print("--------------------------------------------------------\n")
    return spin*MAaMAb


def Lambda(w, a, b, mua, mub, dw, maxw, hwcut):
    """
    Calculate the w dependent Lambda function at zero temperature
    w   energy
    a   "L" or "R"
    b   "L" or "R"
    mua Fermi level of a lead
    mub Fermi level of b lead
    dw  energy grid to do the integration in Lambda
    maxw maximum energy doable
    hwcut   if abs(hw[i]-hw[j])>hwcut, we do not calculate Lambda[i,j]
    """
    # print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")
    #print("Entering Lambda:")
    #print("w=  %f\n"%w)
    #print("a=  %s\n"%a)
    #print("b=  %s\n"%b)
    #print("maxw= %f\n"%maxw)
    nm = len(EPH.hw)
    # outof range set 0
    # the negative part [-maxw,0] will be constructed later from positive part
    if w < 0 or w > maxw:
        return np.zeros((len(EPH.hw), len(EPH.hw)), np.complex)
    l = min(mua-w, mub)
    h = max(mua-w, mub)
    #print("low bound of integration: %f\n"%l)
    #print("high bound of integration: %f\n"%h)
    if l == h:
        return np.zeros((nm, nm), np.complex)
    nw = int(np.floor((h-l)/dw)+1)
    #print("Number of points to do the integration: %i\n"%nw)
    if nw == 1:
        wl = [(h+l)/2]
    else:
        wl = [l+(h-l)*i/(nw-1) for i in range(nw)]
    mama = np.array([calcMAMA(wl[i]+w, wl[i], a, b, hwcut) for i in range(nw)])
    #print("Leaving Lambda:")
    # print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")
    return (mua-mub-w)/4/np.pi**2*np.average(mama, axis=0)


def LambdaFFT(a, b, mua, mub, hwcut):
    """
    Using the formula:
        n_F(w1-mua)-n_F(w2-mub) 
        =n_F(w2-mub)(1-n_F(w1-mua))/n_B(mua-mub-w)  (if mua<=mub, mua-mub-w<0)
    We do not have to split the MAMA part into two terms. This saves calculation time.
    But be careful that, this calculation is right only when mua-mub<w.
    The other part could be recovered by using the symmetry properties of
    Lambda.

    We do an eigen decomposition of matrix M and A, and pick only large eigen values
    in order to make the matrix multiplication faster. The way we do it is as
    follow:

        Tr[(M_k).A1(w2+w).(M_l).A2(w2)]
        = Tr[(Q_k^T).(W_k).(Q_k^*).P_1^T(w2+w).P_1^*(w2+w).
            (Q_l^T).(W_l).(Q_l^*).P_2^T(w2).P_2^*(w2)]
        = Tr[{{(Q_k^*).P_1^T(w2+w)}.{P_1^*(w2+w).(Q_l^T).(W_l)}}.
          {{(Q_l^*).P_2^T(w2)}.{P_2^*(w2).(Q_k^T).(W_k)}}]
        = Tr[MAa(w2+w).MAb(w2)]
    """
    spin = 2  # ELECTRON spin degeneracy
    print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")
    print("Entering Lambda:")
    print(("a=  %s" % a))
    print(("b=  %s" % b))

    E = HS.E.copy()
    cm = EPH.cM
    cv = EPH.cV
    nm = len(EPH.hw)  # number of phonons
    nf = len(E)  # number of energy points
    # number padding zeros, hard coded in myfft.py, has to be this
    npad = (nf/2)*2
    nfft = nf+npad  # add some 'buffer' zeros
    dt = 2*np.pi/nfft/(E[3]-E[2])  # time step of fft
    mfft = myfft(dt, nfft)  # initialise fft class
    MAMA = np.zeros((nm, nm, nf), np.complex)

    # fermi functions
    fermia = np.zeros(nf, np.float)
    fermib = np.zeros(nf, np.float)
    for i in range(nf):
        # 1-n_F(w)
        fermia[i] = 1.0-fermi(E[i], mua, general.T)
        # n_F(w)
        fermib[i] = fermi(E[i], mub, general.T)

    # only lower triangular part of the matrix is calculated
    # i-row index; j-column index
    hw = EPH.hw.copy()
    ntot = nm*(nm+1)/2
    idx = 0
    for i in range(nm):
        for j in range(i+1):
            if general.LongOut:
                print('i-j:', i, j)
            if abs(hw[i]-hw[j]) > hwcut:
                if general.LongOut:
                    print('skip: hw[i]-hw[j]=', abs(hw[i]-hw[j]))
                continue
            if hw[i] < 0 or hw[j] < 0:
                if general.LongOut:
                    print('skip: negative frequency!')
                continue
            # --------------------------------------------------------------------------
            # a
            if a is "L":
                W = HS.WLs
            elif a is "R":
                W = HS.WRs
            else:
                print('a has to be L or R')
                sys.exit()
            MAa = []
            for ii in range(nf):
                mat = fermia[ii]*mm(mm(np.conjugate(cm[i]), np.transpose(W[ii])),
                                    mm(np.conjugate(W[ii]), np.multiply(np.transpose(cm[j]), cv[j])))
                MAa.append(mat.flatten())
            # pad zeros
            MAa = np.array(MAa)
            # MAa=np.concatenate((MAa[0:nf/2],\
            #    np.zeros((npad,len(MAa[0])),np.complex),MAa[nf/2:]),axis=0)

            # MAa(w)->MAa(t)
            MAa = np.transpose(list(map(mfft.iFourier1Dpad, MAa.T)))

            # b
            if b is "L":
                W = HS.WLs
            elif b is "R":
                W = HS.WRs
            else:
                print('b has to be L or R')
                sys.exit()
            MAb = []
            for ii in range(nf):
                mat = fermib[ii]*mm(mm(np.conjugate(cm[j]), np.transpose(W[ii])),
                                    mm(np.conjugate(W[ii]), np.multiply(np.transpose(cm[i]), cv[i])))
                # Tr[AB]=dot(A.flatten(),B.T.flatten())
                mat = np.transpose(mat).flatten()
                MAb.append(mat)
            # pad zeros
            MAb = np.array(MAb)
            # MAb=np.concatenate((MAb[0:nf/2],\
            #    np.zeros((npad,len(MAb[0])),np.complex),MAb[nf/2:]),axis=0)
            # MAb(w)->MAb(t)
            # iFourier1Dpad: pad the array with zeros and do Fourier transform
            # see myfft.py for details
            MAb = np.transpose(list(map(mfft.iFourier1Dpad, MAb.T)))
            # MAb(-t)
            MAb = np.transpose(list(map(trev, MAb.T)))
            # MAa(t)MAb(-t)
            MAabw1 = [np.dot(tmp[0], tmp[1]) for tmp in zip(MAa, MAb)]
            # t->w
            MAabw1 = mfft.Fourier1D(MAabw1)
            # delete the padding zeros
            MAabw1 = np.concatenate(
                (MAabw1[0:nf/2], MAabw1[nf/2+npad:]), axis=0)
            # --------------------------------------------------------------------------

            # MAMA
            MAMA[i, j] = np.array(MAabw1)  # lower triangular element
            if i == j:
                MAMA[i, j] = (MAMA[i, j]+np.conjugate(MAMA[i, j])) * \
                    0.5  # diagonal element
            else:
                # upper triangular element
                MAMA[j, i] = np.conjugate(MAMA[i, j])

            idx = idx+1
            if ntot > 10:
                if(np.mod(idx, ntot/10) == 0):
                    print("%i percent finished\n" % (10*idx/(ntot/10)))

    # sum
    # in the definition of Lambda, we have 1/(2pi)^2
    # 1/(2pi) was taken care in the FFT
    # so we only need to divide by 2pi here
    MAMA = spin*np.array(MAMA)/2.0/np.pi
    # reshape it to (nf,nm,nm)
    MAMA = np.rollaxis(MAMA, 2, 0)

    for i in range(len(E)):
        if mua-mub-E[i] < 0.0:
            MAMA[i] = MAMA[i]/bose(mua-mub-E[i], general.T)
        else:
            MAMA[i] = MAMA[i]*0
    print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")
    return(np.array(MAMA))


def EquLambdaFFT(hwcut, mu0=0):
    """
    The equilibrium part of the Lambda function is real.
    It is the equilibrium friction. We can write it as:
        2\int\frac{dw}{4\pi^2}Tr[M^kA(w)M^l(A(w_-)-A(w_+))]n_F(w-mu0)
    Let A1=A(w)n_F(w-mu0),
    in time domain it becomes:
        (2/2\pi)\int dt Tr[M^k A1(t)M^l A(-t)-M^k A1(-t)M^l A(t)]e^{iwt}
    In the program, MAa=M^k A1, and MAb=M^l A.

    We do an eigen decomposition of matrix M and A, and pick only large eigen values
    in order to make the matrix multiplication faster. The way we do it is as
    follow:

        Tr[(M_k).A1(w2+w).(M_l).A2(w2)]
        = Tr[(Q_k^T).(W_k).(Q_k^*).P_1^T(w2+w).P_1^*(w2+w).
            (Q_l^T).(W_l).(Q_l^*).P_2^T(w2).P_2^*(w2)]
        = Tr[{{(Q_k^*).P_1^T(w2+w)}.{P_1^*(w2+w).(Q_l^T).(W_l)}}.
          {{(Q_l^*).P_2^T(w2)}.{P_2^*(w2).(Q_k^T).(W_k)}}]
        = Tr[MAa(w2+w).MAb(w2)]
    """
    spin = 2  # ELECTRON spin degeneracy
    print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")
    print("Entering EquFriction:")

    E = HS.E.copy()
    cm = EPH.cM
    cv = EPH.cV
    nm = len(EPH.hw)  # number of phonons
    nf = len(E)  # number of energy points
    # number padding zeros, hard coded in myfft.py, has to be this
    npad = (nf/2)*2
    nfft = nf+npad  # add some 'buffer' zeros
    dt = 2*np.pi/nfft/(E[3]-E[2])  # time step of fft
    mfft = myfft(dt, nfft)  # initialise fft class
    MAMA = np.zeros((nm, nm, nf), np.complex)

    # fermi functions
    fermi0 = np.zeros(nf, np.float)
    for i in range(nf):
        # n_F(w)
        fermi0[i] = fermi(E[i], mu0, general.T)

    # only lower triangular part of the matrix is calculated
    # i-row index; j-column index
    hw = EPH.hw.copy()
    ntot = nm*(nm+1)/2
    idx = 0
    for i in range(nm):
        for j in range(i+1):
            if general.LongOut:
                print('i-j:', i, j)
            if abs(hw[i]-hw[j]) > hwcut:
                if general.LongOut:
                    print('skip: hw[i]-hw[j]=', abs(hw[i]-hw[j]))
                continue
            if hw[i] < 0 or hw[j] < 0:
                if general.LongOut:
                    print('skip: negative frequency!')
                continue
            W = HS.Ws
            # --------------------------------------------------------------------------
            # a
            MAa = []
            for ii in range(nf):
                mat = fermi0[ii]*mm(mm(np.conjugate(cm[i]), np.transpose(W[ii])),
                                    mm(np.conjugate(W[ii]), np.multiply(np.transpose(cm[j]), cv[j])))
                MAa.append(mat.flatten())
            # pad zeros
            MAa = np.array(MAa)
            # MAa=np.concatenate((MAa[0:nf/2],\
            #    np.zeros((npad,len(MAa[0])),np.complex),MAa[nf/2:]),axis=0)
            # MAa(w)->MAa(t)
            MAa = np.transpose(list(map(mfft.iFourier1Dpad, MAa.T)))
            # MAa(-t)
            #MAa = np.transpose(map(trev,MAa.T))

            # b
            MAb = []
            for ii in range(nf):
                mat = mm(mm(np.conjugate(cm[j]), np.transpose(W[ii])),
                         mm(np.conjugate(W[ii]), np.multiply(np.transpose(cm[i]), cv[i])))
                # Tr[AB]=dot(A.flatten(),B.T.flatten())
                mat = np.transpose(mat).flatten()
                MAb.append(mat)
            # pad zeros
            MAb = np.array(MAb)
            # MAb=np.concatenate((MAb[0:nf/2],\
            #    np.zeros((npad,len(MAb[0])),np.complex),MAb[nf/2:]),axis=0)
            # MAb(w)->MAb(t)
            MAb = np.transpose(list(map(mfft.iFourier1Dpad, MAb.T)))
            # MAb(-t)
            MAb = np.transpose(list(map(trev, MAb.T)))

            # MAa(t)MAb(-t)
            MAabw1 = np.array([np.dot(tmp[0], tmp[1])
                              for tmp in zip(MAa, MAb)])
            # -MAa(-t)MAb(t)
            MAb = np.transpose(list(map(trev, MAb.T)))  # MAb(t)
            MAa = np.transpose(list(map(trev, MAa.T)))  # MAa(-t)
            MAabw2 = np.array([np.dot(tmp[0], tmp[1])
                              for tmp in zip(MAa, MAb)])

            # MAa(t)MAb(-t)-MAa(-t)MAb(t)
            # t->w
            MAabw = mfft.Fourier1D(MAabw1-MAabw2)
            # delete the padding zeros
            MAabw = np.concatenate((MAabw[0:nf/2], MAabw[nf/2+npad:]), axis=0)
            # --------------------------------------------------------------------------

            # MAMA
            MAMA[i, j] = np.array(MAabw)  # lower triangular element
            MAMA[i, j] = (MAMA[i, j]+np.conjugate(MAMA[i, j]))*0.5  # real
            MAMA[j, i] = MAMA[i, j]

            idx = idx+1
            if ntot > 10:
                if(np.mod(idx, ntot/10) == 0):
                    print("%i percent finished\n" % (10*idx/(ntot/10)))

    # sum
    # in the definition of Lambda, we have 1/(2pi)^2
    # 1/(2pi) was taken care in the FFT
    # so we only need to divide by 2pi here
    MAMA = spin*np.array(MAMA)/2.0/np.pi
    # reshape it to (nf,nm,nm)
    MAMA = np.rollaxis(MAMA, 2, 0)
    print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")
    return(np.array(MAMA))


def NonequLambdaFFT(hwcut, muL=0, muR=0, mu0=0):
    """
    Calculate the nonequilibrium part of the Lambda function, and its Hilbert
    transform.

    We do an eigen decomposition of matrix M and A, and pick only large eigen values
    in order to make the matrix multiplication faster. The way we do it is as
    follow:

        Tr[(M_k).A1(w2+w).(M_l).A2(w2)]
        = Tr[(Q_k^T).(W_k).(Q_k^*).P_1^T(w2+w).P_1^*(w2+w).
            (Q_l^T).(W_l).(Q_l^*).P_2^T(w2).P_2^*(w2)]
        = Tr[{{(Q_k^*).P_1^T(w2+w)}.{P_1^*(w2+w).(Q_l^T).(W_l)}}.
          {{(Q_l^*).P_2^T(w2)}.{P_2^*(w2).(Q_k^T).(W_k)}}]
        = Tr[MAa(w2+w).MAb(w2)]
    """
    spin = 2  # ELECTRON spin degeneracy
    print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")
    print("Entering NonequLambdaFFT:")

    E = HS.E.copy()
    cm = EPH.cM
    cv = EPH.cV
    nm = len(EPH.hw)  # number of phonons
    nf = len(E)  # number of energy points
    # number padding zeros, hard coded in myfft.py, has to be this
    npad = (nf/2)*2
    nfft = nf+npad  # add some 'buffer' zeros
    dt = 2*np.pi/nfft/(E[3]-E[2])  # time step of fft
    mfft = myfft(dt, nfft)  # initialise fft class
    # nonequilibrium part of the Lambda function
    MAMA = np.zeros((nm, nm, nf), np.complex)
    # Hilbert transform of the nonequilibrium part
    HMAMA = np.zeros((nm, nm, nf), np.complex)

    # fermi functions: \Delta n_F(w)=n_F(w,mu)-n_F(w,mu0)
    fermiL = np.zeros(nf, np.float)
    fermiR = np.zeros(nf, np.float)
    for i in range(nf):
        fermiL[i] = fermi(E[i], muL, general.T)-fermi(E[i], mu0, general.T)
        fermiR[i] = fermi(E[i], muR, general.T)-fermi(E[i], mu0, general.T)

    # only lower triangular part of the matrix is calculated
    # i-row index; j-column index
    hw = EPH.hw.copy()
    ntot = nm*(nm+1)/2
    idx = 0
    for i in range(nm):
        for j in range(i+1):
            if general.LongOut:
                print('i-j:', i, j)
            if abs(hw[i]-hw[j]) > hwcut:
                if general.LongOut:
                    print('skip: hw[i]-hw[j]=', abs(hw[i]-hw[j]))
                continue
            if hw[i] < 0 or hw[j] < 0:
                if general.LongOut:
                    print('skip: negative frequency!')
                continue
            W = HS.Ws  # decomposed A
            WL = HS.WLs  # decomposed AL
            WR = HS.WRs  # decomposed AR
            # --------------------------------------------------------------------------
            # a, M^k (AL \Delta n_F^L+AR \Delta n_F^R)
            MAa = []
            for ii in range(nf):
                mat = fermiL[ii]*mm(mm(np.conjugate(cm[i]), np.transpose(WL[ii])),
                                    mm(np.conjugate(WL[ii]), np.multiply(np.transpose(cm[j]), cv[j])))\
                    + fermiR[ii]*mm(mm(np.conjugate(cm[i]), np.transpose(WR[ii])),
                                    mm(np.conjugate(WR[ii]), np.multiply(np.transpose(cm[j]), cv[j])))
                MAa.append(mat.flatten())
            # pad zeros
            MAa = np.array(MAa)
            # MAa=np.concatenate((MAa[0:nf/2],\
            #    np.zeros((npad,len(MAa[0])),np.complex),MAa[nf/2:]),axis=0)

            # MAa(w)->MAa(t)
            MAa = np.transpose(list(map(mfft.iFourier1Dpad, MAa.T)))
            # MAa(-t)
            #MAa = np.transpose(map(trev,MAa.T))

            # --------------------------------------------------------------------------
            # b,Lambda
            MAb = []
            for ii in range(nf):
                mat = mm(mm(np.conjugate(cm[j]), np.transpose(W[ii])),
                         mm(np.conjugate(W[ii]), np.multiply(np.transpose(cm[i]), cv[i])))
                # Tr[AB]=dot(A.flatten(),B.T.flatten())
                mat = np.transpose(mat).flatten()
                MAb.append(mat)
            # pad zeros
            MAb = np.array(MAb)
            # MAb=np.concatenate((MAb[0:nf/2],\
            #    np.zeros((npad,len(MAb[0])),np.complex),MAb[nf/2:]),axis=0)
            # MAb(w)->MAb(t)
            MAb = np.transpose(list(map(mfft.iFourier1Dpad, MAb.T)))
            # MAb(-t)
            MAb = np.transpose(list(map(trev, MAb.T)))

            # ----------------------------------------------------------------
            # Real part : MAa(t)MAb(-t)-MAa(-t)MAb(t)
            # MAa(t)MAb(-t)
            MAabw1 = np.array([np.dot(tmp[0], tmp[1])
                              for tmp in zip(MAa, MAb)])
            # MAa(-t)MAb(t)
            MAb = np.transpose(list(map(trev, MAb.T)))
            MAa = np.transpose(list(map(trev, MAa.T)))
            MAabw2 = np.array([np.dot(tmp[0], tmp[1])
                              for tmp in zip(MAa, MAb)])
            # t->w
            MAabw = mfft.Fourier1D(MAabw1-MAabw2)
            # delete the padding zeros
            MAabw = np.concatenate((MAabw[0:nf/2], MAabw[nf/2+npad:]), axis=0)
            # filling in Re\Delta\Lambda
            MAMA[i, j] = np.array(MAabw)  # lower triangular element
            MAMA[i, j] = (MAMA[i, j]+np.conjugate(MAMA[i, j]))*0.5  # real
            MAMA[j, i] = MAMA[i, j]
            # ---------------------------------------------------------------
            # ---------------------------------------------------------------
            # Imaginary part : MAa(t)MAb(-t)+MAa(-t)MAb(t)
            # t->w
            MAabw = mfft.Fourier1D(MAabw1+MAabw2)
            # delete the padding zeros
            MAabw = np.concatenate((MAabw[0:nf/2], MAabw[nf/2+npad:]), axis=0)
            # Filling in Im\Delta\Lambda
            MAMA[i, j] = MAMA[i, j] + \
                (np.array(MAabw)-np.conjugate(np.array(MAabw)))*0.5
            MAMA[j, i] = MAMA[j, i] - \
                (np.array(MAabw)-np.conjugate(np.array(MAabw)))*0.5
            # ---------------------------------------------------------------

            # --------------------------------------------------------------------------
            # b,HLambda
            Gvs = HS.ReGvs  # Re(Gr), eigenvalues
            Gcs = HS.ReGcs  # Re(Gr), vectors
            MAb = []
            for ii in range(nf):
                mat = mm(mm(np.conjugate(cm[j]), np.multiply(np.transpose(Gcs[ii]), Gvs[ii])),
                         mm(np.conjugate(Gcs[ii]), np.multiply(np.transpose(cm[i]), cv[i])))
                # Tr[AB]=dot(A.flatten(),B.T.flatten())
                mat = np.transpose(mat).flatten()
                MAb.append(mat)
            # pad zeros
            MAb = np.array(MAb)
            # MAb=np.concatenate((MAb[0:nf/2],\
            #    np.zeros((npad,len(MAb[0])),np.complex),MAb[nf/2:]),axis=0)
            # MAb(w)->MAb(t)
            MAb = np.transpose(list(map(mfft.iFourier1Dpad, MAb.T)))
            # MAb(-t)
            MAb = np.transpose(list(map(trev, MAb.T)))

            # -----------------------------------------------------------------
            # Real part of HMAMA
            # MAa(t)MAb(-t)+MAa(-t)MAb(t)
            MAa = np.transpose(list(map(trev, MAa.T)))
            MAabw1 = np.array([np.dot(tmp[0], tmp[1])
                              for tmp in zip(MAa, MAb)])
            MAa = np.transpose(list(map(trev, MAa.T)))
            MAb = np.transpose(list(map(trev, MAb.T)))
            MAabw2 = np.array([np.dot(tmp[0], tmp[1])
                              for tmp in zip(MAa, MAb)])
            # t->w
            MAabw = mfft.Fourier1D(MAabw1+MAabw2)
            # delete the padding zeros
            MAabw = np.concatenate((MAabw[0:nf/2], MAabw[nf/2+npad:]), axis=0)
            # filling in Re\Delta\Lambda
            HMAMA[i, j] = np.array(MAabw)  # lower triangular element
            HMAMA[i, j] = (HMAMA[i, j]+np.conjugate(HMAMA[i, j]))*0.5  # real
            HMAMA[j, i] = HMAMA[i, j]
            # -----------------------------------------------------------------
            # -----------------------------------------------------------------
            # Imaginary part of HMAMA
            # MAa(t)MAb(-t)-MAa(-t)MAb(t)
            # t->w
            MAabw = mfft.Fourier1D(MAabw1-MAabw2)
            # delete the padding zeros
            MAabw = np.concatenate((MAabw[0:nf/2], MAabw[nf/2+npad:]), axis=0)
            # Filling in Im\Delta\Lambda
            HMAMA[i, j] = HMAMA[i, j] + \
                (np.array(MAabw)-np.conjugate(np.array(MAabw)))*0.5
            HMAMA[j, i] = HMAMA[j, i] - \
                (np.array(MAabw)-np.conjugate(np.array(MAabw)))*0.5
            # -----------------------------------------------------------------
            idx = idx+1
            if ntot > 10:
                if(np.mod(idx, ntot/10) == 0):
                    print("%i percent finished\n" % (10*idx/(ntot/10)))

    # sum
    # in the definition of Lambda, we have 1/(2pi)^2
    # 1/(2pi) was taken care in the FFT
    # so we only need to divide by 2pi here
    MAMA = spin*np.array(MAMA)/2.0/np.pi
    # the factor 2 difference is due to H{A}=-2ReG
    HMAMA = spin*np.array(HMAMA)/np.pi
    # reshape it to (nf,nm,nm)
    MAMA = np.rollaxis(MAMA, 2, 0)
    HMAMA = np.rollaxis(HMAMA, 2, 0)
    print("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%\n")
    return(MAMA, HMAMA)


def trev(a):
    """
    from a(t) to get a(-t)
    """
    al = len(a)
    b = np.array(a).copy()
    c = np.array([])
    c = np.append(c, b[0])
    c = np.append(c, b[-1:al/2-1:-1])
    c = np.append(c, b[al/2-1:0:-1])
    return c


def wbLambda(hwcut, outfile, mu0=0):
    """
    Note: already included spin degeneracy in calcMAMA

    calculate eta,xim,xip in wideband approximation
    """
    MLL = calcMAMA(mu0, mu0, "L", "L", hwcut)
    MRR = calcMAMA(mu0, mu0, "R", "R", hwcut)
    MLR = calcMAMA(mu0, mu0, "L", "R", hwcut)
    MRL = calcMAMA(mu0, mu0, "R", "L", hwcut)
    eta = (MLL+MRR+MLR+MRL).real/4/np.pi
    xim = MLR.imag/2/np.pi
    xip = MLR.real/2/np.pi

    # Berry and nonequilibrium renormalization
    cm = EPH.cM
    cv = EPH.cV
    hw = EPH.hw
    nm = len(hw)
    zeta1 = np.zeros(np.shape(eta))  # renormalization
    zeta2 = np.zeros(np.shape(eta))  # berry
    E = HS.E.copy()
    iw = nearest(mu0, E)
    dw = E[iw+1]-E[iw]

    print("position of mu0:", iw)

    WL = HS.WLs[iw]
    WR = HS.WRs[iw]

    ReGv = HS.ReGvs[iw]
    ReGc = HS.ReGcs[iw]
    ReGvp = HS.ReGvs[iw+1]
    ReGcp = HS.ReGcs[iw+1]
    ReGvm = HS.ReGvs[iw-1]
    ReGcm = HS.ReGcs[iw-1]

    for i in range(nm):
        for j in range(i+1):
            if abs(hw[i]-hw[j]) > hwcut:
                continue
            if hw[i] < 0 or hw[j] < 0:
                continue
            # M.(AL(mu0)-AR(mu0))
            mata = mm(mm(np.conjugate(cm[i]), np.transpose(WL)),
                      mm(np.conjugate(WL), np.multiply(np.transpose(cm[j]), cv[j])))\
                - mm(mm(np.conjugate(cm[i]), np.transpose(WR)),
                     mm(np.conjugate(WR), np.multiply(np.transpose(cm[j]), cv[j])))

            # M.ReGr(mu0)
            matb = mm(mm(np.conjugate(cm[j]), np.multiply(np.transpose(ReGc), ReGv)),
                      mm(np.conjugate(ReGc), np.multiply(np.transpose(cm[i]), cv[i])))
            # M.(ReGr(mu0+)-ReGr(mu0-))/dw/2
            matc = (mm(mm(np.conjugate(cm[j]), np.multiply(np.transpose(ReGcp), ReGvp)),
                       mm(np.conjugate(ReGcp), np.multiply(np.transpose(cm[i]), cv[i])))
                    - mm(mm(np.conjugate(cm[j]), np.multiply(np.transpose(ReGcm), ReGvm)),
                         mm(np.conjugate(ReGcm), np.multiply(np.transpose(cm[i]), cv[i]))))/dw/2
            zeta1[i, j] = np.dot(
                mata.flatten(), np.transpose(matb).flatten()).real/np.pi
            zeta1[j, i] = zeta1[i, j]
            zeta2[i, j] = np.dot(
                mata.flatten(), np.transpose(matc).flatten()).imag/np.pi
            if i == j:
                zeta2[j, i] = 0.0
            else:
                zeta2[j, i] = -zeta2[i, j]

    # -----------------------------------------------------------------------------------------
    # eigen analysis

    # Make a doulbe-sized matrix:
    #
    Vmax = 1.0
    nlen = 400
    invQs, nhws = eigenanalysis(Vmax, nlen, hw, eta, xim, zeta1, zeta2)
    # to check with Inelastica
    nph = JouleHeating(Vmax, nlen, hw, eta, xim, xip, zeta1, zeta2, T=4.2)
    blist = invQs[:, 0]
    invQos = invQs[:, 1:]
    nhwos = nhws[:, 1:]
    nphs = nph[:, 1:]
    #
    # -----------------------------------------------------------------------------------------

    # -----------------------------------------------------------------------------------------
    # transform to real space
    # -----------------------------------------------------------------------------------------
    # to real space
    U = general.nU
    eta_r = mm(U.T, eta, U)
    xim_r = mm(U.T, xim, U)
    xip_r = mm(U.T, xip, U)
    # renormalization already included in the structure
    zeta1_r = mm(U.T, zeta1, U)
    zeta2_r = mm(U.T, zeta2, U)

    # -----------------------------------------------------------------------------------------
    # write the Lambda function
    # -----------------------------------------------------------------------------------------
    NCfile = Dataset(outfile, 'w', 'Created '+time.ctime(time.time()))
    #NCfile = nc.NetCDFFile(outfile,'w','Created '+time.ctime(time.time()))
    NCfile.title = 'Output from MAMA.py'
    NCfile.createDimension('NPh', len(EPH.hw))
    NCfile.createDimension('NBias', nlen)
    NCfile.createDimension('one', 1)
    Write2NetCDFFile(NCfile, np.array([mu0]), 'mu0', ('one',), units='eV')
    Write2NetCDFFile(NCfile, eta, 'eta', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, xim, 'xim', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, xip, 'xip', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, zeta1, 'zeta1', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, zeta2, 'zeta2', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, blist, 'blist', ('NBias',), units='V')
    Write2NetCDFFile(NCfile, invQos, 'invQs',
                     ('NBias', 'NPh',), units='unitless')
    Write2NetCDFFile(NCfile, nphs, 'nph', ('NBias', 'NPh',), units='unitless')
    Write2NetCDFFile(NCfile, invQos, 'nhws', ('NBias', 'NPh',), units='eV')

    Write2NetCDFFile(NCfile, eta_r, 'eta_r', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, xim_r, 'xim_r', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, xip_r, 'xip_r', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, zeta1_r, 'zeta1_r', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, zeta2_r, 'zeta2_r', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, U, 'U', ('NPh', 'NPh',),
                     units='0.06466 eV/amu/Angstrom**2')
    Write2NetCDFFile(NCfile, hw, 'hw', ('NPh',), units='eV')

    NCfile.close()
    return(eta, xim, xip, zeta1, zeta2)


# ---------------------------------------------------------------------------

def eigenanalysis(Vmax, nlen, hw, eta, xim, zeta1, zeta2):
    """
    Vmax        max bias
    nlen        number of points in [0:Vmax]
    hw          phonon frequencies
    eta         friction matrix
    xim         NC
    zeta1       renormalization
    zeta2       Berry
    """
    f = open("bias.invQ.dat", "w")
    ff = open("bias.hw.dat", "w")
    nm = len(hw)
    # bias dependent inverse-Q factors
    invQs = np.zeros((nlen, nm+1))
    # bias dependent frequencies
    nhws = np.zeros((nlen, nm+1))
    dynmat = np.diag(hw**2)
    for j in range(nlen):
        tb = Vmax*j/nlen
        tmat = np.zeros((2*nm, 2*nm))
        tmat[:nm, :nm] = -eta-tb*zeta2
        tmat[:nm, nm:] = -dynmat+tb*xim-tb*zeta1
        tmat[nm:, :nm] = np.identity(nm)
        # eigen
        evs = LA.eigvals(tmat)
        # a=-i w, so a.real = w.imag; a.imag=-w.real
        # invQ=-2Im(w)/Re(w)
        invQ = np.zeros(nm+1)
        nhw = np.zeros(nm+1)
        invQ[0] = tb
        nhw[0] = tb
        i = 1
        for a in evs:
            if a.imag < 0:
                invQ[i] = 2*a.real/a.imag
                nhw[i] = -a.imag
                i = i+1
        for i in range(len(invQ)):
            f.write("%s  " % invQ[i])
            ff.write("%s  " % nhw[i])
        f.write("\n")
        ff.write("\n")
        invQs[i] = invQ
        nhws[i] = nhw
    f.close()
    ff.close()
    return invQs, nhws


def JouleHeating(Vmax, nlen, hw, eta, xim, xip, zeta1, zeta2, T=4.2):
    """
    Calculate bias-induced phonon number change

    Vmax        max bias
    nlen        number of points in [0:Vmax]
    hw          phonon frequencies
    eta         friction matrix
    xim         NC
    xip         
    zeta1       renormalization
    zeta2       Berry
    T           temperature
    """
    f = open("bias.nph.dat", "w")
    nm = len(hw)
    # bias dependent phonon number
    nph = np.zeros((nlen, nm+1))
    for i in range(nlen):
        tb = Vmax*i/nlen
        ph = np.zeros((nm+1))
        ph[0] = tb
        for j in range(nm):
            cofp = (hw[j]+tb)*(bose(hw[j]+tb, T)-bose(hw[j], T))
            cofm = (hw[j]-tb)*(bose(hw[j]-tb, T)-bose(hw[j], T))
            cof = cofp+cofm
            if hw[j] <= 0 or eta[j, j] <= 0:
                ph[j+1] = 0.0
            else:
                ph[j+1] = cof*xip[j, j]/hw[j]/eta[j, j]/2+bose(hw[j], T)
        for j in range(len(ph)):
            f.write("%s  " % ph[j])
        f.write("\n")
        nph[i] = ph
    f.close()
    return nph
# ---------------------------------------------------------------------------
# IO functions
# ---------------------------------------------------------------------------


def Write2NetCDFFile(file, var, varLabel, dimensions, units=None, description=None):
    print('Write2NetCDFFile:', varLabel, dimensions)
    tmp = file.createVariable(varLabel, 'd', dimensions)
    tmp[:] = var
    if units:
        tmp.units = units
    if description:
        tmp.description = description


def readHS(fn):
    """
    Read H,S and Sigmas
    To do FFT, we rearrange the energy points according to:
    0 -- dw(N/2-1) , -dw N/2 -- -dw

    If the self-energy at one energy point is not calculated,
    we use the nearest one.
    """
    Bohr2eV = 1.0  # Rydberg constant in eV,  HS is already in eV

    file = Dataset(fn)
    print('Reading ', fn)

    try:
        En = Bohr2eV*np.array(file.variables['ReE'][:])
    except:
        En = Bohr2eV*np.array(file.variables['En'][:, 0])

    npl = len(En)
    dw = En[1]-En[0]
    nw = int(npl/2)*2
    print('number of fourier points:', nw)

    Sig1 = Bohr2eV*(np.array(file.variables['ReSigmaL'][:], np.complex) +
                    1.0j*np.array(file.variables['ImSigmaL'][:], np.complex))
    Sig2 = Bohr2eV*(np.array(file.variables['ReSigmaR'][:], np.complex) +
                    1.0j*np.array(file.variables['ImSigmaR'][:], np.complex))
    ned = len(Sig1[0])
    print("number of basis sets in HSSigmaLR:", ned)

    # save the variables
    #HS.Bias = file.variables['Voltage'][0]
    HS.Bias = 0.

    print('reading HS:')
    # try:
    # new version of tbt by Nick
    HS.H = Bohr2eV*(np.array(file.variables['ReH'][:], np.complex) +
                    +1.0j*np.array(file.variables['ImH'][:], np.complex))
    print('REe', HS.H)

    HS.S = np.array(file.variables['ReS'][:], np.complex) +\
        1.0j*np.array(file.variables['ImS'][:], np.complex)
    # except:
    # old version of tbt
    #    HS.H = Bohr2eV*(np.array(file.variables['H'],np.complex)+\
    #                   1.0j*np.array(file.variables['ImH'][:],np.complex))
    #    HS.S = np.array(file.variables['S'],np.complex)+\
    #                    1.0j*np.array(file.variables['ImS'],np.complex)

    # reorder the energy points in order to do FFT
    HS.E = np.zeros(nw)
    HS.Sig1 = np.zeros((nw, ned, ned), np.complex)
    HS.Sig2 = np.zeros((nw, ned, ned), np.complex)
    for i in range(nw):
        w = dw*i
        if w >= dw*nw/2:
            w = w-nw*dw
        iw = nearest(w, En)
############################################
#	#constant self-energy
#        iw = nearest(general.mu0,En)
#	#iw = 541
############################################
        #HS.E[i] = En[iw]
        HS.E[i] = w
        HS.Sig1[i] = Sig1[iw]
        HS.Sig2[i] = Sig2[iw]
    print('Energy grid :', HS.E)
    file.close()


def ReadEph(mcut):
    NCfile = Dataset(general.PhononNetCDF)
    print('Reading ', general.PhononNetCDF)
    EPH.hw = np.array(NCfile.variables['hw'][:])
    hw = EPH.hw
    # readin M
    M = np.array(NCfile.variables['He_ph'][:])
    # new Inelastica output has an extra spin dimension in He_ph
    msh = np.array(M.shape)
    print("shape of M: ", msh)
    if(len(msh) == 4 and msh[1] == 1):
        M = M[:, 0, :, :]
        print("now shape of M: ", M.shape)
    if(len(msh) == 4 and msh[1] == 2):
        print("spin polarised calculation in PHrun\n")
        print("this feature is not implemented in Lambda.py\n")
        sys.exit()

    # convert unit
    #  Note that we define M as dH/dQ, where Q=\sqrt(m)u is the mass-normalized
    #  displacement. This is different from the output of
    #  Inelastica. The convert coefficient is Sqrt(2 hw)=1/|Q| here.
    for i in range(len(M)):
        if(hw[i] > 0.0):
            M[i] = 0.5*(M[i]+dagger(M[i]))*np.sqrt(2*hw[i])
        else:
            M[i] = 0.5*(M[i]+dagger(M[i]))*np.sqrt(0.0)

    # decomp M
    print('Decomposing e-ph matrix')
    cM = []
    cV = []
    idx = 0
    for mi in M:
        [vm, wm] = cutM(mi, mcut)
        if general.LongOut:
            print("phonon index %i, took %i values\n" % (idx, len(wm)))
        cM.append(wm)
        cV.append(vm)
        idx = idx+1
    #
    EPH.cM = cM
    EPH.cV = cV
    NCfile.close()


def ReadEphSpin(mcut, spin='UP'):
    NCfile = Dataset(general.PhononNetCDF, 'r')
    print('Reading ', general.PhononNetCDF)
    EPH.hw = np.array(NCfile.variables['hw'][:])
    hw = EPH.hw
    # readin M
    M = np.array(NCfile.variables['He_ph'][:])
    # new Inelastica output has an extra spin dimension in He_ph
    msh = np.array(M.shape)
    print("shape of M: ", msh)
    if(len(msh) == 4 and msh[1] == 1):
        M = M[:, 0, :, :]
        print("now shape of M: ", M.shape)
    if(len(msh) == 4 and msh[1] == 2):
        print("spin polarised calculation in PHrun\n")
        if spin is 'UP':
            M = M[:, 0, :, :]
        elif spin is 'DN':
            M = M[:, 1, :, :]
        else:
            print("unknown spin options!\n")
            sys.exit()

    # convert unit
    #  Note that we define M as dH/dQ, where Q=\sqrt(m)u is the mass-normalized
    #  displacement. This is different from the output of
    #  Inelastica. The convert coefficient is Sqrt(2 hw)=1/|Q| here.
    for i in range(len(M)):
        if(hw[i] > 0.0):
            M[i] = 0.5*(M[i]+dagger(M[i]))*np.sqrt(2*hw[i])
        else:
            M[i] = 0.5*(M[i]+dagger(M[i]))*np.sqrt(0.0)

    # decomp M
    print('Decomposing e-ph matrix')
    cM = []
    cV = []
    idx = 0
    for mi in M:
        [vm, wm] = cutM(mi, mcut)
        if general.LongOut:
            print("phonon index %i, took %i values\n" % (idx, len(wm)))
        cM.append(wm)
        cV.append(vm)
        idx = idx+1
    #
    EPH.cM = cM
    EPH.cV = cV
    NCfile.close()


def ReadDynmat(filename, order=None):
    """
    Reads the NetCDF file output from PHrun, Dev*.nc
    return the dynamical matrix in real space

    order:  new order of atoms in siesta index
    """
    file = Dataset(filename)
    print('Reading from %s' % filename)

    hw = np.array(file.variables['hw'][:])
    fullU = np.array(file.variables['U'][:])
    DynamicAtoms = np.array(file.variables['DynamicAtoms'][:])
    nlen = len(fullU)
    file.close()

    idF = DynamicAtoms[0]-1
    idL = DynamicAtoms[-1]

    U = np.zeros([nlen, nlen], np.float)
    for ii in range(len(fullU)):
        U[ii] = fullU[ii][idF:idL].flatten()
    print(U[0])

    print(hw)

    # reorder
    if order is not None:
        n3 = 3*len(order)
        if n3 != len(hw):
            print("ReadDynmat: length of order error!")
            sys.exit()
        idx = ord2idx(order)
        nU = 0.0*U
        for i in range(len(idx)):
            nU[:, i] = U[:, idx[i]]
    else:
        nU = U

    dyn = mm(nU.T, np.diag(hw**2), nU)
    dyn = 0.5*(dyn+dyn.T)
    return dyn, nU, hw
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# general drivers
# ---------------------------------------------------------------------------


def reord(a):
    a = np.array(a)
    l = len(a)
    return np.concatenate(([a[l/2:], a[0:l/2]]))


def mm(* args):
    # mm with arbitrary number of arguments
    tmp = args[0].copy()
    for mat in args[1:]:
        tmp = np.dot(tmp, mat)
    return tmp


def outerAdd(* args):
    # A_ijk=B_i+C_j+D_k
    tmp = args[0]
    for ii in range(1, len(args)):
        tmp = np.add.outer(tmp, args[ii])
    return tmp


def dagger(x):
    return np.conjugate(np.transpose(x))


def ev_sort(eigval, eigvec):
    newval = np.zeros(len(eigval), np.float)
    newvec = np.zeros(eigvec.shape, np.complex)
    index = np.argsort(-eigval)
    for i in index:
        newval[i] = eigval[index[i]]
        newvec[i, :] = eigvec[index[i], :]
    return newval, newvec


def herm(a):
    """
    construct a hermitian matrix from the lower triangular part of a matrix
    """
    b = np.array(a)
    l = len(b)
    c = b.copy()
    # the upper triangular part
    for i in range(l):
        for j in range(i):
            c[j, i] = c[i, j].conjugate()
    # the diagonal part
    for i in range(l):
        c[i, i] = (c[i, i]+c[i, i].conjugate())*0.5
    return c


def nearest(b, bs):
    """
    return the index of the element in bs wich is the nearest to b.
    """
    bsn = np.array(bs)
    bst = abs(bsn-b)
    return(list(bst).index(min(bst)))


# ---------------------------------------------------------------------------


if __name__ == '__main__':
    # profile.run('main()')
    main()
