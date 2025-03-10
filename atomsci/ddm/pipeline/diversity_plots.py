"""
Plotting routines for visualizing chemical diversity of datasets
"""

import os
import sys
import pandas as pd
import numpy as np
import seaborn as sns
import umap
from scipy.stats.kde import gaussian_kde
from scipy.cluster.hierarchy import linkage
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import logging
import argparse
from rdkit import Chem
from rdkit.Chem import AllChem, Draw

from atomsci.ddm.utils import struct_utils
from atomsci.ddm.pipeline import dist_metrics as dm
from atomsci.ddm.pipeline import  chem_diversity as cd
from atomsci.ddm.pipeline import  parameter_parser as parse
from atomsci.ddm.pipeline import  model_datasets as md
from atomsci.ddm.pipeline import  featurization as feat
from atomsci.ddm.utils import datastore_functions as dsf

#matplotlib.style.use('ggplot')
matplotlib.rc('xtick', labelsize=12)
matplotlib.rc('ytick', labelsize=12)
matplotlib.rc('axes', labelsize=12)

logging.basicConfig(format='%(asctime)-15s %(message)s')

ndist_max = 1000000

#------------------------------------------------------------------------------------------------------------------
def plot_dataset_dist_distr(dataset, feat_type, dist_metric, task_name, **metric_kwargs):
    """
    Generate a density plot showing the distribution of distances between dataset feature
    vectors, using the specified feature type and distance metric.
    """
    log = logging.getLogger('ATOM')
    num_cmpds = dataset.X.shape[0]
    if num_cmpds > 50000:
        log.warning("Dataset has %d compounds, too big to calculate distance matrix" % num_cmpds)
        return
    log.warning("Starting distance matrix calculation for %d compounds" % num_cmpds)
    dists = cd.calc_dist_diskdataset(feat_type, dist_metric, dataset, calc_type='all', **metric_kwargs)
    log.warning("Finished calculation of %d distances" % len(dists))
    if len(dists) > ndist_max:
        # Sample a subset of the distances so KDE doesn't take so long
        dist_sample = np.random.choice(dists, size=ndist_max)
    else:
        dist_sample = dists

    dist_pdf = gaussian_kde(dist_sample)
    x_plt = np.linspace(min(dist_sample), max(dist_sample), 500)
    y_plt = dist_pdf(x_plt)
    fig, ax = plt.subplots(figsize=(8.0,8.0))
    ax.plot(x_plt, y_plt, color='forestgreen')
    ax.set_xlabel('%s distance' % dist_metric)
    ax.set_ylabel('Density')
    ax.set_title("%s dataset\nDistribution of %s distances between %s feature vectors" % (
                  task_name, dist_metric, feat_type))
    return dists

#------------------------------------------------------------------------------------------------------------------
def diversity_plots(dset_key, datastore=True, bucket='gsk_ml', title_prefix=None, ecfp_radius=4, out_dir=None, 
                    id_col='compound_id', smiles_col='rdkit_smiles', max_for_mcs=300):
    """
    Plot visualizations of diversity for an arbitrary table of compounds. At minimum, the file should contain
    columns for a compound ID and a SMILES string.
    """
    # Load table of compound names, IDs and SMILES strings
    if datastore:
        cmpd_df = dsf.retrieve_dataset_by_datasetkey(dset_key, bucket)
    else:
        cmpd_df = pd.read_csv(dset_key, index_col=False)
    file_prefix = os.path.splitext(os.path.basename(dset_key))[0]
    if title_prefix is None:
        title_prefix = file_prefix.replace('_', ' ')
    compound_ids = cmpd_df[id_col].values
    smiles_strs = cmpd_df[smiles_col].values
    ncmpds = len(smiles_strs)
    print(ncmpds)
    # Strip salts, canonicalize SMILES strings and create RDKit Mol objects
    print("Canonicalizing molecules...")
    base_mols = [struct_utils.base_mol_from_smiles(smiles) for smiles in smiles_strs]
    for i, mol in enumerate(base_mols):
        if mol is None:
            print('Unable to get base molecule for compound %d = %s' % (i, compound_ids[i]))
    base_smiles = [Chem.MolToSmiles(mol) for mol in base_mols]
    print("Done")

    # Generate ECFP fingerprints
    print("Computing fingerprints...")
    fps = [AllChem.GetMorganFingerprintAsBitVect(mol, ecfp_radius, 1024) for mol in base_mols if mol is not None]
    print("Done")

    if ncmpds <= max_for_mcs:
        # Get MCS distance matrix and draw a heatmap
        print("Computing MCS distance matrix...")
        mcs_dist = dm.mcs(base_mols)
        print("Done")
        cmpd1 = []
        cmpd2 = []
        dist = []
        ind1 = []
        ind2 = []
        for i in range(ncmpds-1):
            for j in range(i+1, ncmpds):
                cmpd1.append(compound_ids[i])
                cmpd2.append(compound_ids[j])
                dist.append(mcs_dist[i,j])
                ind1.append(i)
                ind2.append(j)
        dist_df = pd.DataFrame({'compound_1' : cmpd1, 'compound_2' : cmpd2, 'dist' : dist,
                                'i' : ind1, 'j' : ind2})
        dist_df = dist_df.sort_values(by='dist')
        print(dist_df.head(10))
        if out_dir is not None:
            dist_df.to_csv('%s/%s_mcs_dist_table.csv' % (out_dir, file_prefix), index=False)
            for k in range(10):
                mol_i = base_mols[dist_df.i.values[k]]
                mol_j = base_mols[dist_df.j.values[k]]
                img_file_i = '%s/%d_%s.png' % (out_dir, k, compound_ids[dist_df.i.values[k]])
                img_file_j = '%s/%d_%s.png' % (out_dir, k, compound_ids[dist_df.j.values[k]])
                Draw.MolToFile(mol_i, img_file_i, size=(500,500), fitImage=False)
                Draw.MolToFile(mol_j, img_file_j, size=(500,500), fitImage=False)
    
        mcs_linkage = linkage(mcs_dist, method='complete')
        mcs_df = pd.DataFrame(mcs_dist, columns=compound_ids, index=compound_ids)
        if out_dir is not None:
            pdf_path = '%s/%s_mcs_clustermap.pdf' % (out_dir, file_prefix)
            pdf = PdfPages(pdf_path)
        g = sns.clustermap(mcs_df, row_linkage=mcs_linkage, col_linkage=mcs_linkage, figsize=(12,12), cmap='plasma')
        if out_dir is not None:
            pdf.savefig(g.fig)
            pdf.close()
    
        # Draw a UMAP projection based on MCS distance
        mapper = umap.UMAP(n_neighbors=10, n_components=2, metric='precomputed', random_state=17)
        reps = mapper.fit_transform(mcs_dist)
        rep_df = pd.DataFrame.from_records(reps, columns=['x', 'y'])
        rep_df['compound_id'] = compound_ids
        if out_dir is not None:
            pdf_path = '%s/%s_mcs_umap_proj.pdf' % (out_dir, file_prefix)
            pdf = PdfPages(pdf_path)
        fig, ax = plt.subplots(figsize=(12,12))
        sns.scatterplot(x='x', y='y', data=rep_df, ax=ax)
        ax.set_title("%s, 2D projection based on MCS distance" % title_prefix)
        if out_dir is not None:
            pdf.savefig(fig)
            pdf.close()
            rep_df.to_csv('%s/%s_mcs_umap_proj.csv' % (out_dir, file_prefix), index=False)

    # Get Tanimoto distance matrix
    print("Computing Tanimoto distance matrix...")
    tani_dist = dm.tanimoto(fps)
    print("Done")
    # Draw a UMAP projection based on Tanimoto distance
    mapper = umap.UMAP(n_neighbors=10, n_components=2, metric='precomputed', random_state=17)
    reps = mapper.fit_transform(tani_dist)
    rep_df = pd.DataFrame.from_records(reps, columns=['x', 'y'])
    rep_df['compound_id'] = compound_ids
    if out_dir is not None:
        pdf_path = '%s/%s_tani_umap_proj.pdf' % (out_dir, file_prefix)
        pdf = PdfPages(pdf_path)
    fig, ax = plt.subplots(figsize=(12,12))
    sns.scatterplot(x='x', y='y', data=rep_df, ax=ax)
    ax.set_title("%s, 2D projection based on Tanimoto distance" % title_prefix)
    if out_dir is not None:
        pdf.savefig(fig)
        pdf.close()

    # Draw a cluster heatmap based on Tanimoto distance
    tani_linkage = linkage(tani_dist, method='complete')
    tani_df = pd.DataFrame(tani_dist, columns=compound_ids, index=compound_ids)
    if out_dir is not None:
        pdf_path = '%s/%s_tanimoto_clustermap.pdf' % (out_dir, file_prefix)
        pdf = PdfPages(pdf_path)
    g = sns.clustermap(tani_df, row_linkage=tani_linkage, col_linkage=tani_linkage, figsize=(12,12), cmap='plasma')
    if out_dir is not None:
        pdf.savefig(g.fig)
        pdf.close()



#------------------------------------------------------------------------------------------------------------------
def sa200_diversity_plots(ecfp_radius=6):
    """
    Plot visualizations of diversity for the 208 compounds selected for phenotypic assays.
    """
    sa200_file = '/ds/projdata/gsk_data/ExperimentalDesign/AS200_TS_12Oct18.csv'
    out_dir = '/usr/local/data/sa200'
    file_prefix = 'sa200'
    title_prefix = 'Phenotypic assay compound set'
    diversity_plots(sa200_file, datastore=False, bucket=None, title_prefix=title_prefix, out_dir=out_dir, ecfp_radius=ecfp_radius, 
                    smiles_col='canonical_smiles')

#------------------------------------------------------------------------------------------------------------------
def bsep_diversity_plots(ecfp_radius=6):
    """
    Plot visualizations of diversity for the compounds in the BSEP PIC50 dataset.
    """
    dset_key = 'singletask_liability_datasets/ABCB11_Bile_Salt_Export_Pump_BSEP_membrane_vesicles_Imaging_PIC50.csv'
    out_dir = '/usr/local/data/bsep'
    os.makedirs(out_dir, exist_ok=True)
    title_prefix = 'ABCB11_Bile_Salt_Export_Pump_BSEP_membrane_vesicles_Imaging_PIC50 compound set'
    diversity_plots(dset_key, datastore=True, bucket='gsk_ml', title_prefix=title_prefix, out_dir=out_dir, ecfp_radius=ecfp_radius)


#------------------------------------------------------------------------------------------------------------------
def obach_diversity_plots(ecfp_radius=6):
    """
    Plot visualizations of diversity for the compounds in the Obach, Lombardo et al PK dataset
    """
    # TODO: Put this dataset in the datastore where everybody else can see it
    cmpd_file = '/usr/local/data/diversity_plots/obach/LombardoSupplemental_Data_rdsmiles.csv'
    out_dir = '/usr/local/data/diversity_plots/obach'
    os.makedirs(out_dir, exist_ok=True)
    file_prefix = 'obach'
    title_prefix = 'Obach PK compound set'
    id_col = 'Name' 
    smiles_col='rdkit_smiles'


    # Load table of compound names, IDs and SMILES strings
    cmpd_df = pd.read_csv(cmpd_file, index_col=False)
    compound_ids = cmpd_df[id_col].values
    smiles_strs = cmpd_df[smiles_col].values
    ncmpds = len(smiles_strs)

    # Strip salts, canonicalize SMILES strings and create RDKit Mol objects
    print("Canonicalizing molecules...")
    base_mols = [struct_utils.base_mol_from_smiles(smiles) for smiles in smiles_strs]
    for i, mol in enumerate(base_mols):
        if mol is None:
            print('Unable to get base molecule for compound %d = %s' % (i, compound_ids[i]))
    base_smiles = [Chem.MolToSmiles(mol) for mol in base_mols]
    print("Done")

    # Generate ECFP fingerprints
    print("Computing fingerprints...")
    fps = [AllChem.GetMorganFingerprintAsBitVect(mol, ecfp_radius, 1024) for mol in base_mols if mol is not None]
    print("Done")

    # Get Tanimoto distance matrix
    print("Computing Tanimoto distance matrix...")
    tani_dist = dm.tanimoto(fps)
    print("Done")
    # Draw a UMAP projection based on Tanimoto distance
    mapper = umap.UMAP(n_neighbors=10, n_components=2, metric='precomputed', random_state=17)
    reps = mapper.fit_transform(tani_dist)
    rep_df = pd.DataFrame.from_records(reps, columns=['x', 'y'])
    rep_df['compound_id'] = compound_ids
    if out_dir is not None:
        pdf_path = '%s/%s_tani_umap_proj.pdf' % (out_dir, file_prefix)
        pdf = PdfPages(pdf_path)
    fig, ax = plt.subplots(figsize=(12,12))
    sns.scatterplot(x='x', y='y', data=rep_df, ax=ax)
    ax.set_title("%s, 2D projection based on Tanimoto distance" % title_prefix)

    main_rep_df = rep_df[(rep_df.x > -20) & (rep_df.y > -20)]
    fig, ax = plt.subplots(figsize=(12,12))
    sns.scatterplot(x='x', y='y', data=main_rep_df, ax=ax)
    ax.set_title("%s, main portion, 2D projection based on Tanimoto distance" % title_prefix)
    if out_dir is not None:
        pdf.savefig(fig)

    pdf.close()

    # Draw a cluster heatmap based on Tanimoto distance
    tani_linkage = linkage(tani_dist, method='complete')
    tani_df = pd.DataFrame(tani_dist, columns=compound_ids, index=compound_ids)
    if out_dir is not None:
        pdf_path = '%s/%s_tanimoto_clustermap.pdf' % (out_dir, file_prefix)
        pdf = PdfPages(pdf_path)
    g = sns.clustermap(tani_df, row_linkage=tani_linkage, col_linkage=tani_linkage, figsize=(12,12), cmap='plasma')
    if out_dir is not None:
        pdf.savefig(g.fig)
        pdf.close()



#------------------------------------------------------------------------------------------------------------------
def solubility_diversity_plots(ecfp_radius=6):
    """
    Plot visualizations of diversity for the compounds in the Delaney and GSK aqueous solubility datasets
    """
    data_dir = '/ds/data/gsk_data/GSK_datasets/solubility'
    cmpd_file = '%s/delaney-processed.csv' % data_dir
    out_dir = '/usr/local/data/diversity_plots/solubility'
    os.makedirs(out_dir, exist_ok=True)
    file_prefix = 'delaney'
    title_prefix = 'Delaney solubility compound set'
    diversity_plots(cmpd_file, file_prefix, title_prefix, out_dir=out_dir, ecfp_radius=ecfp_radius, id_col='Compound ID')
    cmpd_file = '%s/ATOM_GSK_Solubility_Aqueous.csv' % data_dir
    title_prefix = 'GSK Aqueous Solubility compound set'
    file_prefix = 'gsk_aq_sol'
    diversity_plots(cmpd_file, file_prefix, title_prefix, out_dir=out_dir, ecfp_radius=ecfp_radius, id_col='compound_id')

#------------------------------------------------------------------------------------------------------------------
def compare_solubility_datasets(ecfp_radius=6):
    """
    Plot projections of Delaney and GSK solubility datasets using the same UMAP projectors.
    """
    data_dir = '/ds/data/gsk_data/GSK_datasets/solubility'
    del_cmpd_file = '%s/delaney-processed.csv' % data_dir
    out_dir = '/usr/local/data/diversity_plots/solubility'
    smiles_col='rdkit_smiles'
    del_id_col = 'Compound ID'

    # Load table of compound names, IDs and SMILES strings
    del_cmpd_df = pd.read_csv(del_cmpd_file, index_col=False)
    del_compound_ids = del_cmpd_df[del_id_col].values
    del_smiles_strs = del_cmpd_df[smiles_col].values

    # Strip salts, canonicalize SMILES strings and create RDKit Mol objects
    base_mols = [struct_utils.base_mol_from_smiles(smiles) for smiles in del_smiles_strs]
    for i, mol in enumerate(base_mols):
        if mol is None:
            print('Unable to get base molecule for compound %d = %s' % (i, del_compound_ids[i]))
    base_smiles = [Chem.MolToSmiles(mol) for mol in base_mols]
    del_fps = [AllChem.GetMorganFingerprintAsBitVect(mol, ecfp_radius, 1024) for mol in base_mols if mol is not None]


    gsk_cmpd_file = '%s/ATOM_GSK_Solubility_Aqueous.csv' % data_dir
    gsk_cmpd_df = pd.read_csv(gsk_cmpd_file, index_col=False)
    gsk_smiles_strs = gsk_cmpd_df[smiles_col].values
    gsk_id_col = 'compound_id'
    # Check for common structures between datasets
    dup_smiles = list(set(gsk_smiles_strs) & set(del_smiles_strs))
    print("GSK and Delaney compound sets have %d SMILES strings in common" % len(dup_smiles))
    if len(dup_smiles) > 0:
        gsk_cmpd_df = gsk_cmpd_df[~gsk_cmpd_df.rdkit_smiles.isin(dup_smiles)]
    gsk_smiles_strs = gsk_cmpd_df[smiles_col].values
    gsk_compound_ids = gsk_cmpd_df[gsk_id_col].values
    base_mols = [struct_utils.base_mol_from_smiles(smiles) for smiles in gsk_smiles_strs]
    for i, mol in enumerate(base_mols):
        if mol is None:
            print('Unable to get base molecule for compound %d = %s' % (i, del_compound_ids[i]))
    base_smiles = [Chem.MolToSmiles(mol) for mol in base_mols]
    gsk_fps = [AllChem.GetMorganFingerprintAsBitVect(mol, ecfp_radius, 1024) for mol in base_mols if mol is not None]

    # Train a UMAP projector with Delaney set, then use it to project both data sets
    del_mapper = umap.UMAP(n_neighbors=10, n_components=2, metric='jaccard', random_state=17)
    del_reps = del_mapper.fit_transform(del_fps)
    gsk_reps = del_mapper.transform(gsk_fps)
    del_rep_df = pd.DataFrame.from_records(del_reps, columns=['x', 'y'])
    del_rep_df['compound_id'] = del_compound_ids
    del_rep_df['dataset'] = 'Delaney'
    gsk_rep_df = pd.DataFrame.from_records(gsk_reps, columns=['x', 'y'])
    gsk_rep_df['compound_id'] = gsk_compound_ids
    gsk_rep_df['dataset'] = 'GSK Aq Sol'
    rep_df = pd.concat((del_rep_df, gsk_rep_df), ignore_index=True)
    dataset_pal = {'Delaney' : 'forestgreen', 'GSK Aq Sol' : 'orange'}
    pdf_path = '%s/delaney_gsk_aq_sol_umap_proj.pdf' % out_dir
    pdf = PdfPages(pdf_path)
    fig, ax = plt.subplots(figsize=(12,12))
    g = sns.scatterplot(x='x', y='y', ax=ax, hue='dataset', style='dataset', palette=dataset_pal, data=rep_df)
    ax.set_title("Solubility dataset fingerprints, UMAP projection trained on Delaney data", fontdict={'fontsize' : 12})
    pdf.savefig(fig)
    pdf.close()

    # Train a UMAP projector with GSK set, then use it to project both data sets
    gsk_mapper = umap.UMAP(n_neighbors=10, n_components=2, metric='jaccard', random_state=17)
    gsk_reps = gsk_mapper.fit_transform(gsk_fps)
    del_reps = gsk_mapper.transform(del_fps)
    del_rep_df = pd.DataFrame.from_records(del_reps, columns=['x', 'y'])
    del_rep_df['compound_id'] = del_compound_ids
    del_rep_df['dataset'] = 'Delaney'
    gsk_rep_df = pd.DataFrame.from_records(gsk_reps, columns=['x', 'y'])
    gsk_rep_df['compound_id'] = gsk_compound_ids
    gsk_rep_df['dataset'] = 'GSK Aq Sol'
    rep_df = pd.concat((gsk_rep_df, del_rep_df), ignore_index=True)
    dataset_pal = {'Delaney' : 'forestgreen', 'GSK Aq Sol' : 'orange'}
    pdf_path = '%s/gsk_aq_sol_delaney_umap_proj.pdf' % out_dir
    pdf = PdfPages(pdf_path)
    fig, ax = plt.subplots(figsize=(12,12))
    g = sns.scatterplot(x='x', y='y', ax=ax, hue='dataset', style='dataset', palette=dataset_pal, data=rep_df)
    ax.set_title("Solubility dataset fingerprints, UMAP projection trained on GSK aqueous solubility data", fontdict={'fontsize' : 12})
    pdf.savefig(fig)
    pdf.close()



#------------------------------------------------------------------------------------------------------------------
def compare_obach_gsk_aq_sol(ecfp_radius=6):
    """
    Plot projections of Obach and GSK solubility datasets using the same UMAP projectors.
    """
    obach_cmpd_file = '/usr/local/data/diversity_plots/obach/LombardoSupplemental_Data_rdsmiles.csv'
    out_dir = '/usr/local/data/diversity_plots/obach'
    obach_id_col = 'Name' 
    smiles_col='rdkit_smiles'

    # Load table of compound names, IDs and SMILES strings
    obach_cmpd_df = pd.read_csv(obach_cmpd_file, index_col=False)
    # Sample the same number of compounds as in the GSK set
    obach_cmpd_df = obach_cmpd_df.sample(n=732, axis=0)
    obach_compound_ids = obach_cmpd_df[obach_id_col].values
    obach_smiles_strs = obach_cmpd_df[smiles_col].values

    # Strip salts, canonicalize SMILES strings and create RDKit Mol objects
    base_mols = [struct_utils.base_mol_from_smiles(smiles) for smiles in obach_smiles_strs]
    for i, mol in enumerate(base_mols):
        if mol is None:
            print('Unable to get base molecule for compound %d = %s' % (i, obach_compound_ids[i]))
    base_smiles = [Chem.MolToSmiles(mol) for mol in base_mols]
    obach_fps = [AllChem.GetMorganFingerprintAsBitVect(mol, ecfp_radius, 1024) for mol in base_mols if mol is not None]

    # Load the GSK dataset
    gsk_data_dir = '/ds/data/gsk_data/GSK_datasets/solubility'
    gsk_cmpd_file = '%s/ATOM_GSK_Solubility_Aqueous.csv' % gsk_data_dir
    gsk_cmpd_df = pd.read_csv(gsk_cmpd_file, index_col=False)
    gsk_smiles_strs = gsk_cmpd_df[smiles_col].values
    gsk_id_col = 'compound_id'
    # Check for common structures between datasets
    dup_smiles = list(set(gsk_smiles_strs) & set(obach_smiles_strs))
    print("GSK and Obach compound sets have %d SMILES strings in common" % len(dup_smiles))
    if len(dup_smiles) > 0:
        gsk_cmpd_df = gsk_cmpd_df[~gsk_cmpd_df.rdkit_smiles.isin(dup_smiles)]
    gsk_smiles_strs = gsk_cmpd_df[smiles_col].values
    gsk_compound_ids = gsk_cmpd_df[gsk_id_col].values
    base_mols = [struct_utils.base_mol_from_smiles(smiles) for smiles in gsk_smiles_strs]
    for i, mol in enumerate(base_mols):
        if mol is None:
            print('Unable to get base molecule for compound %d = %s' % (i, obach_compound_ids[i]))
    base_smiles = [Chem.MolToSmiles(mol) for mol in base_mols]
    gsk_fps = [AllChem.GetMorganFingerprintAsBitVect(mol, ecfp_radius, 1024) for mol in base_mols if mol is not None]

    # Train a UMAP projector with Obach set, then use it to project both data sets
    obach_mapper = umap.UMAP(n_neighbors=10, n_components=2, metric='jaccard', random_state=17)
    obach_reps = obach_mapper.fit_transform(obach_fps)
    gsk_reps = obach_mapper.transform(gsk_fps)
    obach_rep_df = pd.DataFrame.from_records(obach_reps, columns=['x', 'y'])
    obach_rep_df['compound_id'] = obach_compound_ids
    obach_rep_df['dataset'] = 'Obach'
    gsk_rep_df = pd.DataFrame.from_records(gsk_reps, columns=['x', 'y'])
    gsk_rep_df['compound_id'] = gsk_compound_ids
    gsk_rep_df['dataset'] = 'GSK Aq Sol'
    rep_df = pd.concat((obach_rep_df, gsk_rep_df), ignore_index=True)
    #main_rep_df = rep_df[(rep_df.x > -20) & (rep_df.y > -20)]
    dataset_pal = {'Obach' : 'blue', 'GSK Aq Sol' : 'orange'}
    pdf_path = '%s/obach_gsk_aq_sol_umap_proj.pdf' % out_dir
    pdf = PdfPages(pdf_path)
    fig, ax = plt.subplots(figsize=(12,12))
    g = sns.scatterplot(x='x', y='y', ax=ax, hue='dataset', style='dataset', palette=dataset_pal, data=rep_df)
    ax.set_title("Obach and GSK solubility dataset fingerprints, UMAP projection trained on Obach data", fontdict={'fontsize' : 12})
    pdf.savefig(fig)
    pdf.close()

#------------------------------------------------------------------------------------------------------------------
def liability_dset_diversity(bucket='gsk_ml', feat_type='descriptors', dist_metric='cosine', **metric_kwargs):
    """
    Load datasets from datastore, featurize them, and plot distributions of their inter-compound
    distances.
    """
    log = logging.getLogger('ATOM')
    ds_client = dsf.config_client()
    ds_table = dsf.search_datasets_by_key_value(key='param', value=['PIC50','PEC50'], operator='in', 
                                                bucket=bucket, client=ds_client)
    dset_keys = ds_table.dataset_key.values
    metadata = ds_table.metadata.values
    split = 'random'
    task_names = []
    num_cmpds = []
    for i, dset_key in enumerate(dset_keys):
        md_dict = dsf.metadata_to_dict(metadata[i])
        task_name = md_dict['task_name']
        num_cmpds = md_dict['CMPD_COUNT'][0]
        log.warning("Loading dataset for %s, %d compounds" % (task_name, num_cmpds))
        dset_df = dsf.retrieve_dataset_by_datasetkey(dset_key, bucket, ds_client)
        dataset_dir = os.path.dirname(dset_key)
        dataset_file = os.path.basename(dset_key)
        if feat_type == 'descriptors':
            params = argparse.Namespace(dataset_dir=dataset_dir,
                            dataset_file=dataset_file,
                            y=task_name,
                            bucket=bucket,
                            descriptor_key='all_GSK_Compound_2D_3D_MOE_Descriptors_Scaled_With_Smiles_And_Inchi',
                            descriptor_type='MOE',
                            splitter=split,
                            id_col='compound_id',
                            smiles_col='rdkit_smiles',
                            featurizer='descriptors',
                            prediction_type='regression', 
                            system='twintron-blue',
                            datastore=True,
                            transformers=True)
        elif feat_type == 'ECFP':
            params = argparse.Namespace(dataset_dir=dataset_dir,
                            dataset_file=dataset_file,
                            y=task_name,
                            bucket=bucket,
                            splitter=split,
                            id_col='compound_id',
                            smiles_col='rdkit_smiles',
                            featurizer='ECFP',
                            prediction_type='regression', 
                            system='twintron-blue',
                            datastore=True,
                            ecfp_radius=2, ecfp_size=1024, 
                            transformers=True)
        else:
            log.error("Feature type %s not supported" % feat_type)
            return
        log.warning("Featurizing data with %s featurizer" % feat_type)
        model_dataset = md.MinimalDataset(params)
        model_dataset.get_featurized_data(dset_df)
        num_cmpds = model_dataset.dataset.X.shape[0]
        if num_cmpds > 50000:
            log.warning("Too many compounds to compute distance matrix: %d" % num_cmpds)
            continue
        plot_dataset_dist_distr(model_dataset.dataset, feat_type, dist_metric, task_name, **metric_kwargs)

    # ------------------------------------------------------------------------------------------------------------------
    def get_dset_diversity(dset_key, ds_client, bucket='gsk_ml', feat_type='descriptors', dist_metric='cosine',
                           **metric_kwargs):
        """
        Load datasets from datastore, featurize them, and plot distributions of their inter-compound
        distances.
        """
        log = logging.getLogger('ATOM')
    
        dset_df = dsf.retrieve_dataset_by_datasetkey(dset_key, bucket, ds_client)
    
        if feat_type == 'descriptors':
            params = parse.wrapper(dict(
                dataset_key=dset_key,
                bucket=bucket,
                descriptor_key='/ds/projdata/gsk_data/GSK_Descriptors/GSK_2D_3D_MOE_Descriptors_By_Variant_ID_With_Base_RDKit_SMILES.feather',
                descriptor_type='moe',
                featurizer='descriptors',
                system='twintron-blue',
                datastore=True,
                transformers=True))
        elif feat_type == 'ECFP':
            params = parse.wrapper(dict(
                dataset_key=dset_key,
                bucket=bucket,
                featurizer='ECFP',
                system='twintron-blue',
                datastore=True,
                ecfp_radius=2,
                ecfp_size=1024,
                transformers=True))
        else:
            log.error("Feature type %s not supported" % feat_type)
            return
        metadata = dsf.get_keyval(dataset_key=dset_key, bucket=bucket)
        if 'id_col' in metadata.keys():
            params.id_col = metadata['id_col']
        if 'param' in metadata.keys():
            params.response_cols = [metadata['param']]
        elif 'response_col' in metadata.keys():
            params.response_cols = [metadata['response_col']]
        elif 'response_cols' in metadata.keys():
            params.response_cols = metadata['response_cols']
    
        if 'smiles_col' in metadata.keys():
            params.smiles_col = metadata['smiles_col']
    
        if 'class_number' in metadata.keys():
            params.class_number = metadata['class_number']
        params.dataset_name = dset_key.split('/')[-1].rstrip('.csv')
    
        log.warning("Featurizing data with %s featurizer" % feat_type)
        featurization = feat.create_featurization(params)
        model_dataset = md.MinimalDataset(params, featurization)
        model_dataset.get_featurized_data(dset_df)
        num_cmpds = model_dataset.dataset.X.shape[0]
        if num_cmpds > 50000:
            log.warning("Too many compounds to compute distance matrix: %d" % num_cmpds)
            return
        # plot_dataset_dist_distr(model_dataset.dataset, feat_type, dist_metric, params.response_cols, **metric_kwargs)
        dists = cd.calc_dist_diskdataset('descriptors', dist_metric, model_dataset.dataset, calc_type='all')
        import scipy
        dists = scipy.spatial.distance.squareform(dists)
        res_dir = '/ds/projdata/gsk_data/model_analysis/'
        plt_dir = '%s/Plots' % res_dir
        file_prefix = dset_key.split('/')[-1].rstrip('.csv')
        mcs_linkage = linkage(dists, method='complete')
        pdf_path = '%s/%s_mcs_clustermap.pdf' % (plt_dir, file_prefix)
        pdf = PdfPages(pdf_path)
        g = sns.clustermap(dists, row_linkage=mcs_linkage, col_linkage=mcs_linkage, figsize=(12, 12), cmap='plasma')
        if plt_dir is not None:
            pdf.savefig(g.fig)
            pdf.close()
        return dists
