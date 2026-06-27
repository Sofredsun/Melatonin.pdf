# DATASETS NAMES
DATASETS = ['oxazolidinone', 'benzimidazole', 'cocrystals', 'complexes', 'nanozymes', 'magnetic', 'cytotoxicity', 'seltox', 'synergy']

# DATASETS_IDS
DATASETS_IDS = {'oxazolidinone': 'ai-chem/Oxazolidinones', 
                'benzimidazole': 'ai-chem/Benzimidazoles', 
                'cocrystals': 'ai-chem/Co-crystals', 
                'complexes': 'ai-chem/Complexes', 
                'nanozymes': 'ai-chem/Nanozymes', 
                'magnetic': 'ai-chem/Nanomag', 
                'cytotoxicity': 'ai-chem/Cytotox', 
                'seltox': 'ai-chem/SelTox', 
                'synergy': 'ai-chem/Synergy'}

# EXTRACTION
EXTRACTED_COLUMNS = {
    'oxazolidinone': ['compound_id', 'smiles', 'target_type', 'target_relation', 'target_value', 'target_units', 'bacteria'],
    'benzimidazole': ['compound_id', 'smiles', 'target_type', 'target_relation', 'target_value', 'target_units', 'bacteria'],
    'cocrystals': ['name_cocrystal', 'ratio_cocrystal', 'name_drug', 'SMILES_drug', 'name_coformer', 'SMILES_coformer', 'photostability_change'],
    'complexes': ['compound_id', 'compound_name', 'SMILES', 'SMILES_type', 'target'],
    'nanozymes': ['formula', 'activity', 'syngony', 'length', 'width', 'depth', 'surface', 'km_value', 'km_unit', 'vmax_value', 'vmax_unit', 'reaction_type', 'c_min', 'c_max', 'c_const', 'c_const_unit', 'ccat_value', 'ccat_unit', 'ph', 'temperature'],
    'magnetic': ["name", "np_core", "np_shell", "core_shell_formula", "np_shell_2", "np_hydro_size", "xrd_scherrer_size", "emic_size", "space_group_core", "space_group_shell", "squid_sat_mag", "squid_rem_mag", "exchange_bias_shift_Oe", "vertical_loop_shift_M_vsl_emu_g", "hc_kOe", "squid_h_max", "zfc_h_meas", "instrument", "fc_field_T", "squid_temperature", "coercivity", "htherm_sar", "mri_r1", "mri_r2"],
    'cytotoxicity': ["material", "shape", "coat_functional_group", "synthesis_method", "surface_charge", "core_nm", "size_in_medium_nm", "hydrodynamic_nm", "potential_mv", "zeta_in_medium_mv", "no_of_cells_cells_well", "human_animal", "cell_source", "cell_tissue", "cell_morphology", "cell_age", "time_hr", "concentration", "test", "test_indicator", "viability_%"],
    'seltox': ["np", "coating", "bacteria", "mdr", "strain", "np_synthesis", "method", "mic_np_µg_ml", "concentration", "zoi_np_mm", "np_size_min_nm", "np_size_max_nm", "np_size_avg_nm", "shape", "time_set_hours", "zeta_potential_mV", "solvent_for_extract", "temperature_for_extract_C", "duration_preparing_extract_min", "precursor_of_np", "concentration_of_precursor_mM", "hydrodynamic_diameter_nm", "ph_during_synthesis"],
    'synergy': ["NP", "bacteria", "strain", "NP_synthesis", "drug", "drug_dose_µg_disk", "NP_concentration_µg_ml", "NP_size_min_nm", "NP_size_max_nm", "NP_size_avg_nm", "shape", "method", "ZOI_drug_mm_or_MIC _µg_ml", "error_ZOI_drug_mm_or_MIC_µg_ml", "ZOI_NP_mm_or_MIC_np_µg_ml", "error_ZOI_NP_mm_or_MIC_np_µg_ml", "ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml", "error_ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml", "fold_increase_in_antibacterial_activity", "zeta_potential_mV", "MDR", "FIC", "effect", "time_hr", "coating_with_antimicrobial_peptide_polymers", "combined_MIC", "peptide_MIC", "viability_%",  "viability_error"]
}

NUMERIC_COLUMNS = {
    'oxazolidinone': ['target_value'],
    'benzimidazole': ['target_value'],
    'cocrystals': [],
    'complexes': ['target'],
    'nanozymes': ['length', 'width', 'depth', 'km_value', 'vmax_value', 'c_min', 'c_max', 'c_const', 'ccat_value', 'ph', 'temperature'],
    'magnetic': ["np_hydro_size", "xrd_scherrer_size", "emic_size", "squid_sat_mag", "squid_rem_mag", "exchange_bias_shift_Oe", "vertical_loop_shift_M_vsl_emu_g", "hc_kOe", "squid_h_max", "zfc_h_meas", "fc_field_T", "squid_temperature", "coercivity", "htherm_sar", "mri_r1", "mri_r2"],
    'cytotoxicity': ["core_nm", "size_in_medium_nm", "hydrodynamic_nm", "potential_mv", "zeta_in_medium_mv", "no_of_cells_cells_well", "time_hr", "concentration", "viability_%"],
    'seltox': ["mdr", "mic_np_µg_ml", "concentration", "zoi_np_mm", "np_size_min_nm", "np_size_max_nm", "np_size_avg_nm", "time_set_hours", "zeta_potential_mV", "temperature_for_extract_C", "duration_preparing_extract_min", "concentration_of_precursor_mM", "hydrodynamic_diameter_nm", "ph_during_synthesis"],
    'synergy': ["drug_dose_µg_disk", "NP_concentration_µg_ml", "NP_size_min_nm", "NP_size_max_nm", "NP_size_avg_nm", "ZOI_drug_mm_or_MIC _µg_ml", "error_ZOI_drug_mm_or_MIC_µg_ml", "ZOI_NP_mm_or_MIC_np_µg_ml", "error_ZOI_NP_mm_or_MIC_np_µg_ml", "ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml", "error_ZOI_drug_NP_mm_or_MIC_drug_NP_µg_ml", "fold_increase_in_antibacterial_activity", "zeta_potential_mV", "FIC", "time_hr", "combined_MIC", "peptide_MIC", "viability_%",  "viability_error"]    
}

SMILES_COLS = {
    'oxazolidinone': ['smiles'],
    'benzimidazole': ['smiles'],
    'cocrystals': ['SMILES_drug', 'SMILES_coformer'],
    'complexes': ['SMILES'],   
    'nanozymes': [],
    'magnetic': [],
    'cytotoxicity': [],
    'seltox': [],
    'synergy': []
}

# ARTICLES
MAGNETIC_ARTICLES = ['j.msec.2009.09.003.pdf', 'd0na00820f.pdf', '1.2739217.pdf',
       'nn305991e.pdf', 'nano12183159.pdf', 'd2ra04454d.pdf',
       'nano12173023.pdf', 'nano7120415.pdf',
       'j.colsurfa.2023.132281.pdf', 's41598-018-19676-5.pdf',
       'matersci.2022005.pdf', 'j.jmmm.2019.165783.pdf', 'abc386.pdf',
       'PhysRevB.80.064427.pdf', 's41598-024-65757-z.pdf',
       'nn101643u.pdf', 'magnetochemistry7110146.pdf', 'nano14060482.pdf',
       'PhysRevB.94.054432.pdf', 'physrevb.92.054416.pdf',
       'c5nr00055f.pdf', 'nano12030456.pdf', 'thno.14280.pdf',
       'nano7080225.pdf', 'd1nr03335b.pdf', 'j.bioactmat.2021.09.028.pdf',
       '9.0000561.pdf', 'acsomega.0c03332.pdf', 'nano13050880.pdf',
       '1.4982893.pdf', '1.4926424.pdf', 'abce87.pdf',
       'adfm.201403436.pdf', 'PhysRevB.94.184410.pdf',
       'acs.jpcc.7b01469.pdf', 'advs.201901800.pdf', '1.2736303.pdf',
       'ncomms15468.pdf', 'nano7030061.pdf', 'nano12020262.pdf',
       'nl102623x.pdf', 'j.jmmm.2019.165940.pdf',
       'j.jmmm.2007.01.007.pdf', '245002.pdf', 's12951-022-01562-y.pdf',
       'C7NR03740F.pdf', 'applnano1010007.pdf', 'nn5038652.pdf',
       'c5nr00774g.pdf', 'nano11030627.pdf', 'nano10050907.pdf',
       'j.rinp.2024.107469.pdf', 'D2TC03144B.pdf', 'ma15062228.pdf',
       'nano12193304.pdf', 'acsomega.8b03004.pdf', 'ab7e6e.pdf',
       's40580-014-0032-4.pdf']

SELTOX_ARTICLES = ['156_1-s2.0-S294982952400024X-main.pdf',
       '145_1-s2.0-S187853522200079X-main.pdf',
       '176_1-s2.0-S1350417724001718-main.pdf',
       '198_1-s2.0-S2590207524000170-main.pdf',
       '108_JPAM_Vol_15_Issue4_p_1907-1914.pdf', '138_d2ma00613h.pdf',
       '98_ijpr-19-70.pdf', '154_1-s2.0-S2405844022012981-main.pdf',
       '4_antibiotics-11-01219-v2.pdf',
       '188_nanomaterials-08-00586-v2.pdf',
       '171_1-s2.0-S2211926423001625-main.pdf',
       '204_1-s2.0-S1658361217300483-main.pdf',
       '141_1-s2.0-S1687157X23007692-main.pdf',
       '99_10.3390@nano10081614.pdf',
       '190_1-s2.0-S1878535222001587-main.pdf',
       '157_1-s2.0-S1018364720304092-main.pdf', '125_848.pdf',
       '194_1-s2.0-S003257912300514X-main.pdf', '164_c9na00017h.pdf',
       '31_thirumurugan2016.pdf',
       '93_green-synthesis-of-silver-nanoparticles-using-cinnamomum-zylinicum-and-their-synergistic-effect-against-multidrug-resistance-bacte.pdf',
       '146_1-s2.0-S2405844024071470-main.pdf',
       '158_1-s2.0-S1878535223006561-main.pdf',
       '23_1-s2.0-S0944501315300136-main.pdf', '202_d3ra07819a.pdf',
       '210_JPAM_Vol_15_Issue4_p_1907-1914.pdf',
       '29_10.3390@polym13040659.pdf',
       '132_1-s2.0-S1018364722005547-main.pdf',
       '218_1-s2.0-S240584402302950X-main.pdf',
       '150_1-s2.0-S2666934X23000259-main.pdf', '103_alekish2018.pdf',
       '152_d1ra00488c.pdf', '122_1-s2.0-S2405844022007605-main.pdf',
       '126_1-s2.0-S2405844023062692-main.pdf',
       '16_IJN-49284-combined-efficacy-of-biologically-synthesized-silver-nanopar_081913.pdf',
       '201_1-s2.0-S1013905218301780-main.pdf',
       '72_10.1186@s12951-020-0588-6.pdf', '139_d2ra01734b.pdf',
       '211_fbioe-10-820218.pdf', '112_1-s2.0-S1018364721004110-main.pdf',
       '175_1-s2.0-S1878535224000637-main.pdf',
       '33_s11274-017-2406-3.pdf',
       '186_1-s2.0-S1319562X2030139X-main.pdf',
       '114_10.1016@j.heliyon.2019.e02980.pdf',
       '155_1-s2.0-S0928098723003111-main.pdf',
       '134_1-s2.0-S2211715624002066-main.pdf',
       '159_1-s2.0-S1878535214002482-main.pdf',
       '149_1-s2.0-S2773111123000293-main.pdf',
       '143_1-s2.0-S235218642100715X-main.pdf',
       '121_1-s2.0-S2405665024000490-main.pdf',
       '217_1-s2.0-S1018364723004214-main.pdf',
       '166_1-s2.0-S1018364721002494-main.pdf',
       '144_1-s2.0-S2405844023099796-main.pdf', '97_boda2015.pdf',
       '173_1-s2.0-S2666086524000134-main.pdf',
       '151_1-s2.0-S1319562X19301676-main.pdf', '39_PM-13-828.pdf',
       '165_1-s2.0-S2590156724000173-main.pdf',
       '148_1-s2.0-S2352952022000469-main.pdf',
       '116_1-s2.0-S2215017X2300036X-main.pdf',
       '177_1-s2.0-S1687157X23008247-main.pdf',
       '117_1-s2.0-S240584402401291X-main.pdf',
       '118_1-s2.0-S1319610314001586-main.pdf',
       '128_1-s2.0-S2211715623002229-main.pdf',
       '219_1-s2.0-S1018364720303001-main.pdf']

# PROMPT
PROMPT_DESCRIPTION = "You are a domain-specific chemical information extraction assistant."