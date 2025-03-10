import argparse
import json
import sys
import re
import logging
import datetime

log = logging.getLogger('ATOM')
# TODO: mjt, do we need to deal with parameters with options?
# e.g. ["dk","d","r","s","f","n","dd","sl","y"]

# Parameters that may take lists of values, usually but not always in the context of a hyperparam search

convert_to_float_list = {'dropouts','weight_init_stddevs','bias_init_consts','learning_rate',
                         'umap_targ_wt', 'umap_min_dist', 'dropout_list','weight_decay_penalty',
                         'xgb_learning_rate',
                         'xgb_gamma',
                         "xgb_min_child_weight",
                         "xgb_subsample",
                         "xgb_colsample_bytree"
                         }
convert_to_int_list = {'layer_sizes','rf_max_features','rf_estimators', 'rf_max_depth',
                       'umap_dim', 'umap_neighbors', 'layer_nums', 'node_nums',
                       "xgb_max_depth",  "xgb_n_estimators"}
convert_to_numeric_list = convert_to_float_list | convert_to_int_list
keep_as_list = {'dropouts','weight_init_stddevs','bias_init_consts',
                'layer_sizes','dropout_list','layer_nums'}
not_a_list_outside_of_hyperparams = {'learning_rate','weight_decay_penalty',
                                     'xgb_learning_rate',
                                     'xgb_gamma',
                                     "xgb_min_child_weight",
                                     "xgb_subsample",
                                     "xgb_colsample_bytree",
                                     "xgb_max_depth",  "xgb_n_estimators"
                                     }
convert_to_str_list = \
    {'response_cols','model_type','featurizer','splitter','umap_metric','weight_decay_penalty_type','descriptor_type'}
not_a_str_list_outside_of_hyperparams = \
    {'model_type','featurizer','splitter','umap_metric','weight_decay_penalty_type','descriptor_type'}

#**********************************************************************************************************
def to_str(params_obj):
    """ Converts a namespace.argparse object or a dict into a string for command line input

        Args:
            params_obj (argparse.Namespace or dict): an argparse namespace object or dict to be converted into a
            command line input.
                E.g. params_obj = argparse.Namespace(arg1 = val1, arg2 = val2, arg3 = val3) OR
                params_obj = {'arg1':val1, 'arg2':val2, 'arg3':val3}

        Returns:
            str_params (str): parameters in string format
                E.g. str_params = '--arg1 val1 --arg2 val2 --arg3 val3'

    """
    # This command converts the namespace_obj to a dict, with the spaces replaced with
    # a temporary string.
    if type(params_obj) == dict:
        strobj = dict_to_list(params_obj,replace_spaces=True)
    else:
        strobj = dict_to_list(vars(params_obj),replace_spaces=True)
    separator = " "
    str_params = separator.join(strobj)
    return str_params



#**********************************************************************************************************
def wrapper(*any_arg):
    """"Wrapper to handle the ParseParams class. Calls the correct method depending on the input argument type

        Args:
            *any_arg: any single input of a str, dict, argparse.Namespace, or list

        Returns:
            argparse.Namespace: a Namespace.argparse object containing default parameters + user specified parameters

        Raises:
            TypeError: Input argument must be a configuration file (str), dict, argparse.Namespace, or list

    """
    if len(any_arg) == 1:
        inp_arg = any_arg[0]
        if isinstance(inp_arg,str):
            list_inp = parse_config_file(config_file_path = inp_arg)
            return parse_command_line(list_inp)
        elif isinstance(inp_arg, (dict,argparse.Namespace)):
            list_inp = parse_namespace(inp_arg)
            return parse_command_line(list_inp)
        elif isinstance(inp_arg, list):
            # This conditional statement checks for the positional argument '--config_file'
            # and parses the input .json configuration file into a list type input
            if inp_arg[0] == '--config_file' or inp_arg[0] == '--config':
                list_inp = parse_config_file(config_file_path = inp_arg[1])
                # If there are additional arguments beyond the config_file input
                # the following if statement properly appends the remaining arguments
                #
                if len(inp_arg) > 2:
                    just_args = [x for x in inp_arg[2:] if "--" in x]
                    for item in just_args:
                        if item in list_inp:
                            idx = list_inp.index(item)
                            if "--" in list_inp[idx+1]:
                                list_inp[idx:idx+1] = []
                            else:
                                list_inp[idx:idx+2] = []
                    list_inp += inp_arg[2:]
                return parse_command_line(list_inp)
            elif len(inp_arg) == 1:
                if inp_arg[0][0:9] == 'Namespace':
                    eval_arg = eval('argparse.' + inp_arg[0])
                    print(eval_arg)
                else:
                    eval_arg = eval(inp_arg[0])
                if isinstance(eval_arg, (dict,argparse.Namespace)):
                    list_inp = parse_namespace(eval_arg)
                    return parse_command_line(list_inp)
                else:
                    return parse_command_line(eval_arg)
            else:
                return parse_command_line(inp_arg)
        else:
            raise TypeError("Input argument must be a configuration file (str), dict, argparse.Namespace, or list")
    else:
        raise TypeError("Input argument must be a configuration file (str), dict, argparse.Namespace, or list")

#**********************************************************************************************************


def parse_config_file(config_file_path):
    """"Method to convert a .json configuration file to a Namespace object. Does the following conversions:
    .json -> hierarchical dict -> flat dict -> dict_to_list.
    WARNING: if there are two identical parameters on the same hierarchical level in the config.json, the .json will
    inherently silence the parameter higher up on the list without flagging a duplication. However, duplicate
    parameters in two different hierarchies or subdictionaries will be flagged by this parser.

    Args:
        config_file_path(str): PATH to configuration .json file

    Returns:
        argparse.Namespace: a Namespace.argparse object containing default parameters + user specified parameters

    """
    # Loads the .json config file
    with open(config_file_path) as f:
        config = json.loads(f.read())

    # If the config file is a hierarchical dict, it flattens the dictionary, otherwise, the dict is unchanged
    flat_dict = flatten_dict(config, {})

    # there are several optional naming conventions for parameters, the following lines of code replace the optional
    # names with the expected parameter names
    replace_json_names_dict = \
        {'dataset_bucket':'bucket','feat_type':'featurizer','y':'response_cols','optimizer':'optimizer_type'}
    orig_keys = list(flat_dict.keys())
    for key, vals in replace_json_names_dict.items():
        if key in orig_keys:
            flat_dict[vals] = flat_dict.pop(key)

    #dictionary comprehension that retains only the keys that are in the accepted list of parameters
    if 'hyperparam' in orig_keys and flat_dict['hyperparam'] == True:
        default = list_defaults(hyperparam=True)
    else:
        default = list_defaults()
    keep = list(vars(default).keys())
    newdict = {k: flat_dict[k] for k in keep if k in flat_dict}

    # Writes a warning for any arguments that are not in the default list of parameters
    extra_keys = [x for x in list(flat_dict.keys()) if x not in newdict.keys()]
    if len(extra_keys)>0:
        log.warning(str(extra_keys) + " are not part of the accepted list of parameters and will be ignored")
    newdict['config_file'] = config_file_path
    return dict_to_list(newdict)

#***********************************************************************************************************
def flatten_dict(inp_dict,newdict = {}):

    """Method to flatten a hierarchical dictionary. Used in parse_config_file(). Throws error if there are duplicated
    keys in the dictionary. WARNING: immediately throws error upon first detection of duplications.

    Args:
        inp_dict(dict): hierarchical dictionary

        newdict(empty dict): empty dictionary, name of output flattened dictionary

    Returns:
        newdict(dict): Flattened dictionary.

    """

    for key, val in inp_dict.items():
        if isinstance(val,dict):
            flatten_dict(val,newdict)
        else:
            if key in newdict and newdict[key] != val:
                log.warning(str(key) + " appears several times. Overwriting with value: " + str(val))
                newdict[key] = val
            else:
                newdict[key] = val
    return newdict

#***********************************************************************************************************

def parse_namespace(namespace_params=None):
    """Method to convert namespace object to dictionary, then pass the value to dict_to_list. Will simply pass a
    dictionary

    Args:
        namespace_params(dictionary or namespace.argparse object)

    Returns:
        argparse.Namespace: a Namespace.argparse object containing default parameters + user specified parameters

    """
    if namespace_params is None:
        return dict_to_list(namespace_params)
    if isinstance(namespace_params,argparse.Namespace):
        namespace_params = vars(namespace_params)
    # If the namespace object or dictionary is a hierarchical dict, it flattens the dictionary, otherwise, the dict
    # is unchanged

    flat_dict = flatten_dict(namespace_params, {})

    # there are several optional naming conventions for parameters, the following lines of code replace the optional
    # names with the expected parameter names
    replace_json_names_dict = \
        {'dataset_bucket':'bucket','feat_type':'featurizer','y':'response_cols','optimizer':'optimizer_type'}
    orig_keys = list(flat_dict.keys())
    for key, vals in replace_json_names_dict.items():
        if key in orig_keys:
            flat_dict[vals] = flat_dict.pop(key)

    #dictionary comprehension that retains only the keys that are in the accepted list of parameters
    default = list_defaults()
    keep = list(vars(default).keys())
    newdict = {k: flat_dict[k] for k in keep if k in flat_dict}

    # Writes a warning for any arguments that are not in the default list of parameters
    extra_keys = [x for x in list(flat_dict.keys()) if x not in newdict.keys()]
    if len(extra_keys)>0:
        log.warning(str(extra_keys) + " are not part of the accepted list of parameters and will be ignored")

    return dict_to_list(newdict)

#***********************************************************************************************************

def dict_to_list(inp_dictionary,replace_spaces=False):
    """Method to convert dictionary to a modified list of strings for input to argparse. Adds a '--' in front of keys
    in the dictionary.

    Args:
        inp_dictionary (dict): Flat dictionary of parameters

        replae_spaces (bool): A flag for replace spaces with replace_spaces_str for handling spaces in command line.

    Returns:
        (list): a list of default parameters + user specified parameters

        None if inp_dictionary is None

    """

    #if replace_spaces is true, replaces spaces with replace_spaces_str for os command line calls
    replace_spaces_str = "@"
    if not isinstance(inp_dictionary,dict):
        raise ValueError("input to dict_to_list should be a dictionary!")

    # Handles optional names for the dictionary.
    optional_names_dict = \
        {'dataset_bucket':'bucket','feat_type':'featurizer','y':'response_cols','optimizer':'optimizer_type'}
    orig_keys = list(inp_dictionary.keys())
    for key, vals in optional_names_dict.items():
        if key in orig_keys:
            inp_dictionary[vals] = inp_dictionary.pop(key)
    temp_list_to_command_line = []

    # Special case handling for arguments that are False or True by default
    default_false = ['previously_split','use_shortlist','datastore', 'save_results','verbose', 'hyperparam', 'split_only', 'rerun']
    default_true = ['transformers','previously_featurized','uncertainty']
    for key, value in inp_dictionary.items():
        if key in default_false:
            true_options = ['True','true','ture','TRUE','Ture']
            if str(value) in true_options:
                temp_list_to_command_line.append('--' + str(key))
        elif key in default_true:
            false_options = ['False','false','flase','FALSE','Flase']
            if str(value) in false_options:
                temp_list_to_command_line.append('--' + str(key))
        else:
            temp_list_to_command_line.append('--' + str(key))
            # Special case handling for null values
            null_options = ['null','Null','none','None','N/A','n/a','NaN','nan','NAN','NONE','NULL']
            if str(value) in null_options:
                temp_list_to_command_line.append('None')
            elif isinstance(value, list):
                sep = ","
                newval = sep.join([str(item) for item in value])
                if replace_spaces == True:
                    temp_list_to_command_line.append(newval.replace(" ",replace_spaces_str))
                else:
                    temp_list_to_command_line.append(newval)
            else:
                newval = str(value)
                if replace_spaces == True:
                    temp_list_to_command_line.append(newval.replace(" ",replace_spaces_str))
                else:
                    temp_list_to_command_line.append(newval)
    return temp_list_to_command_line

#***********************************************************************************************************

def list_defaults(hyperparam=False):
    """Creates temporary required variables, to generate a Namespace.argparse object of defaults.

    Returns:
        argparse.Namespace: a Namespace.argparse object containing default parameters + user specified parameters

    """
    #TODO: These required_vars are no longer required, but are very convenient for testing.
    # Replace these vars after refactoring testing.
    if hyperparam:
        required_vars = ['--dataset_key','/ds/data/public/delaney/delaney-processed.csv',
                     '--bucket','gsk_ml', '--hyperparam']
    else:
        required_vars = ['--dataset_key','/ds/data/public/delaney/delaney-processed.csv',
                     '--bucket','gsk_ml']
    return parse_command_line(required_vars)
#***********************************************************************************************************

def parse_command_line(args=None):
    """Parses a command line argument or a specifically formatted list of strings into a Namespace.argparse object.

    String input is in the following format:
        args = ['--arg1','val1','--arg2','val2','--arg3','val3']

    Args:
        args(None or list): If args is none, parse_command_line parses sys.argv if it . If args is a list, the list is
        parsed

    Returns:
        parsed_args (argparse.Namespace): an object containing default parameters + user specific parameters

    """

    # The following conditional checks for duplicates in the input list
    if args is not None:
        if isinstance(args, str):
            newlist = re.split(" ",args)
        else:
            newlist = args
        just_args = [x for x in newlist if "--" in x]
        duplicates = set([x for x in just_args if just_args.count(x) > 1])
        if len(duplicates) > 0:
            raise ValueError(str(duplicates) + " appears several times. ")

    parser = get_parser()
    parsed_args = parser.parse_args(args)

    return postprocess_args(parsed_args)

def get_parser():
    """Method that performs the actual parsing of pre-processed parameters. Modify this method to add/change/remove
    parameters

    Args: None

    Returns:
        parser (argparse.Namespace): an object containing default parameters + user specific parameters

    """
    # Conditional help strings for layer sizes and dropouts. Modify these dictionaries to change the help string
    layer_size_options = {'graphconv': '[64,64,128]', 'ecfp': '[1000,500]', 'descriptors': '[200,100]'}
    dropout_options = {'graphconv': '[0,0,0]','non-graphconv':'[0.40,0.40]'}
    weight_init_stddevs_options = {'all': '[0.02,0.02]'}
    bias_init_consts_options = {'all':'[1.0,1.0]'}
    parser = argparse.ArgumentParser(
        description=
        'Parses a command line argument or a specifically formatted list of strings into a Namespace.argparse object.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    # **********************************************************************************************************
    # training_dataset_parameters
    parser.add_argument(
        '--bucket', dest='bucket', default='gsk_ml', required=False,
        help='Name of datastore bucket. Specific to LLNL datastore system.')
    parser.add_argument(
        '--dataset_key', '-dk', dest='dataset_key', required=False, default = None,
        help='Datastore key (LLNL system) or file path for dataset.')
    parser.add_argument(
        '--dataset_name', dest='dataset_name', default=None,
        help='Parameter for overriding the output files/dataset object names. Default is set within model_pipeline.')
    parser.add_argument(
        '--dataset_oid', dest='dataset_oid', default=None, required=False,
        help='OID of the model dataset inserted into the datastore. Specific to LLNL datastore system.')
    parser.add_argument(
        '--datastore', dest='datastore', action='store_true',
        help='Boolean flag for using an input file from the LLNL specific datastore system based on a key of'
             'dataset_key')
    parser.set_defaults(datastore=False)
    parser.add_argument(
        '--id_col', dest='id_col', default='compound_id',
        help='Name of column containing compound IDs. Will default to compound_id if not specified')
    parser.add_argument(
        '--min_compound_number', dest='min_compound_number', default=200, type=int,
        help='Minimum number of dataset compounds considered adequate for model training. A warning message will be'
             'issued if the dataset size is less than this.')
    parser.add_argument(
        '--response_cols', '-y', dest='response_cols', type=str,
        help='name of column(s) containing response values. Will default to last column if not specified. '
             'Input as a string of comma separated values for hyperparameter search. Can be input as a comma '
             'separated list for hyperparameter search (e.g. \'column1\',\'column2\')')
    parser.add_argument(
        '--save_results', dest='save_results', action='store_true',
        help='Save model results to Mongo DB. LLNL model_tracker system specific')
    parser.add_argument(
        '--smiles_col', dest='smiles_col', default='rdkit_smiles',
        help='Name of column containing SMILES strings. Will default to "rdkit_smiles" if not specified')

    # **********************************************************************************************************
    # model_building_parameters: autoencoders
    parser.add_argument(
        '--autoencoder_bucket', dest='autoencoder_bucket',
        default='gsk_ml',
        help='datastore bucket for the autoencoder file. Specific to LLNL datastore system. TODO: Not yet implemented')
    parser.add_argument(
        '--autoencoder_key', dest='autoencoder_key', default=None,
        help='Base of key for the autoencoder. TODO: Not yet implemented')
    parser.add_argument(
        '--autoencoder_type', dest='autoencoder_type',
        default='molvae',
        help='Type of autoencoder being used as features. TODO: Not yet implemented')
    parser.add_argument(
        '--mol_vae_model_file', dest='mol_vae_model_file', default=None,
        help='Trained model HDF5 file path, only needed for MolVAE featurizer')

    # **********************************************************************************************************
    # model_building_parameters: classifiers
    parser.add_argument(
        '--class_number', dest='class_number', type=int, required=False, default=2,
        help='User specified number of classes')
    parser.add_argument(
        '--class_name', dest='class_name',required=False, default=None,
        help='User specified class name. TODO: referenced in hyperparameter_search_wrapper, in test_mlmt_client_metadata.')
    # **********************************************************************************************************
    # model_building_parameters: descriptors
    parser.add_argument(
        '--descriptor_bucket', dest='descriptor_bucket',
        default='gskdata',
        help='Datastore bucket for the descriptor file. Specific to LLNL datastore system.')
    parser.add_argument(
        '--descriptor_key', dest='descriptor_key', default=None,
        help='Base of key for descriptor table file. Subset files will be prepended with "subset"'
             'and appended with the dataset name. Specific to LLNL datastore system.')
    # TODO: REMOVE DESCRIPTOR_OID, ingested in model_pipeline but is metadata as part of the model_tracker
    parser.add_argument(
        '--descriptor_oid', dest='descriptor_oid',
        default=None,
        help='dataset_oid for the descriptor file in the datastore')
    parser.add_argument(
        '--descriptor_spec_bucket', dest='descriptor_spec_bucket',
        default='public',
        help='Bucket where descriptor specification is located for a descriptor type. Specific to LLNL datastore'
             'system.')
    parser.add_argument(
        '--descriptor_spec_key', dest='descriptor_spec_key',
        default='descriptor_sets_sources_by_descr_type.csv',
        help='Bucket where descriptor specification is located for a descriptor type. Specific to LLNL datastore'
             'system.')
    parser.add_argument(
        '--descriptor_type', dest='descriptor_type', default='moe',
        help='Type of descriptors being used as features, e.g. moe, dragon7, used when featurizer = "descriptors". '
             'Sets the subclass within featurizer.py')

    # **********************************************************************************************************
    # model_building_parameters: ecfp
    parser.add_argument(
        '--ecfp_radius', dest='ecfp_radius', type=int, default=2,
        help='Radius used for ECFP generation')
    parser.add_argument(
        '--ecfp_size', dest='ecfp_size', type=int, default=1024,
        help='Size of ECFP bit vectors')

    # **********************************************************************************************************
    # model_building_parameters: general
    parser.add_argument(
        '--featurizer', '-f', dest='featurizer', default=None, type=str,
        help='Type of featurizer to use on chemical structures. Current supported options: '
             '["ecfp","graphconv","molvae","computed_descriptors","descriptors"]. Further information on '
             'descriptors are in descriptor_type. Options are used to set the featurization subclass in the '
             'create_featurization method of featurization.py. Can be input as a comma separated list for '
             'hyperparameter search (e.g. \'ecfp\',\'molvae\')')
    parser.add_argument(
        '--model_choice_score_type', dest='model_choice_score_type', required=False, default=None,
        help='Type of score function used to choose best epoch and/or hyperparameters (defaults to "roc_auc" '
             'for classification and "r2" for regression). ')
    parser.add_argument(
        '--model_type', dest='model_type', default=None, type=str,
        help='Type of model to fit (NN, RF, or xgboost). The model_type sets the model subclass in model_wrapper. '
             'Can be input as a comma separated list for hyperparameter search (e.g. \'NN\',\'RF\')')
    parser.add_argument(
        '--prediction_type', dest='prediction_type', required=False, default='regression',
        choices=['regression', 'classification'],
        help='Sets the prediction type of the model to a choice between ["regresion","classification"]. Used as '
             'a flag for model behavior throughout the pipeline.')
    parser.add_argument(
        '--previously_featurized', dest='previously_featurized', action='store_false',
        help='Boolean flag for loading in previously featurized data files. If set to True, the method'
             'get_featurized_data within model_datasets will attempt to load the featurized dataset' 
             'associated with the given dataset_oid parameter')
    parser.set_defaults(previously_featurized=True)
    parser.add_argument(
        '--uncertainty', dest='uncertainty', action='store_false',
        help='Boolean flag for computing uncertainty estimates for regression model predictions. Will also change the' 
             'default values for dropouts if set to True.')
    parser.set_defaults(uncertainty=True)
    parser.add_argument(
        '--verbose', dest='verbose', action='store_true',
        help='True/False flag for setting verbosity')
    parser.set_defaults(verbose=False)

    # **********************************************************************************************************
    # model_building_parameters: graphconv
    parser.add_argument(
        '--optimizer_type', dest='optimizer_type', required=False, default='adam',
        help='Optimizer specific for graph conv, defaults to "adam"')

    # **********************************************************************************************************
    # model_building_parameters: mordred
    parser.add_argument(
        '--mordred_cpus', dest='mordred_cpus', type=int, default=None,
        help='Max number of CPUs to use for Mordred descriptor computations. None means use all available')

    # **********************************************************************************************************
    # model_building_parameters: neural_nets
    parser.add_argument(
        '--baseline_epoch', '-b', dest='baseline_epoch', type=int, default=30,
        help='Baseline epoch at which to evaluate performance for DNN models')
    parser.add_argument(
        '--batch_size', dest='batch_size', type=int, required=False, default=50,
        help='Sets the model batch size within model_wrapper')

    temp_bias_init_consts_string = [key + ':' + value + ',' for key, value in bias_init_consts_options.items()]
    separator = " "
    bias_init_consts_help_string = \
        ('Comma-separated list of initial bias parameters per layer for dense NN models with conditional values. ' 
         'Defaults to [1.0]*len(layer_sizes). Must be same length as layer_sizes. Can be input as a space-separated ' 
         'list of comma-separated lists for hyperparameters (e.g. \'1.0,1.0 0.9,0.9 0.8,0.9\'). Default behavior is' 
         ' set within __init__ method of DCNNModelWrapper.  '
         + separator.join(temp_bias_init_consts_string)).rstrip(',')
    parser.add_argument(
        '--bias_init_consts', dest='bias_init_consts', required=False, default=None,
        help=bias_init_consts_help_string)

    temp_dropout_string = [key + ':' + value + ',' for key, value in dropout_options.items()]
    separator = " "
    dropout_help_string = \
        ('Comma-separated list of dropout rates per layer for NN models with default values conditional on featurizer.' 
         ' Default behavior is controlled in model_wrapper.py. Must be same length as layer_sizes. Can be input as ' 
         'a space-separated list of comma-separated lists for hyperparameters (e.g. \'0.4,0.4 0.2,0.2 0.3,0.3\'). ' 
         'Default behavior is set within __init__ method of DCNNModelWrapper. Defaults: '
         + separator.join(temp_dropout_string)).rstrip(',')
    parser.add_argument(
        '--dropouts', dest='dropouts', required=False, default=None,
        help=dropout_help_string)

    temp_layer_size_string = [key + ':' + value + ',' for key,value in layer_size_options.items()]
    separator = " "
    layer_size_help_string = \
        ('Comma-separated list of layer sizes for NN models with default values conditional on featurizer. Must be' 
         ' same length as layer_sizes. Can be input as a space-separated list of comma-separated lists for ' 
         'hyperparameters (e.g. \'64,16 200,100 1000,500\'). Default behavior is set within __init__ method of ' 
         'DCNNModelWrapper. Defaults: '
         + separator.join(temp_layer_size_string)).rstrip(',')
    parser.add_argument(
        '--layer_sizes', dest='layer_sizes', required=False, default=None,
        help=layer_size_help_string)

    parser.add_argument(
        '--learning_rate', dest='learning_rate', required=False, default='0.0005',
        help='Learning rate for dense NN models. Input as comma separated floats for hyperparameters ' 
             '(e.g. \'0.0005,0.0004,0.0003\')')
    parser.add_argument(
        '--max_epochs', dest='max_epochs', type=int, default=30,
        help='Maximum number of training epochs to run for DNN models')
    parser.add_argument(
        '--weight_decay_penalty', dest='weight_decay_penalty', required=False, default='0.0001',
        help='weight_decay_penalty: float. The magnitude of the weight decay penalty to use. ' 
             'Can be input as a comma separated list of strings for hyperparameter search ' 
             '(e.g. \'0.0001,0.0002,0.0003\')')
    parser.add_argument(
        '--weight_decay_penalty_type', dest='weight_decay_penalty_type', default='l2', type=str,
        help='weight_decay_penalty_type: str. The type of penalty to use for weight decay, either "l1" or "l2". ' 
             'Can be input as a comma separated list for hyperparameter search (e.g. \'l1,l2\')')

    temp_weight_init_stddevs_string = [key + ':' + value + ',' for key, value in weight_init_stddevs_options.items()]
    separator = " "
    weight_init_stddevs_help_string = \
        ('Comma-separated list of standard deviations per layer for initializing weights in dense NN models with ' 
         'conditional values. Must be same length as layer_sizes. Can be input as a space-separated list of ' 
         'comma-separated lists for hyperparameters (e.g. \'0.001,0.001 0.002,0.002 0.03,003\'). Default behavior is ' 
         'set within __init__ method of DCNNModelWrapper. Defaults: '
         + separator.join(temp_weight_init_stddevs_string)).rstrip(',')
    parser.add_argument(
        '--weight_init_stddevs', dest='weight_init_stddevs', required=False, default=None,
        help=weight_init_stddevs_help_string)

    # **********************************************************************************************************
    # model_building_parameters: random_forest
    parser.add_argument(
        '--rf_estimators', dest='rf_estimators', default='500',
        help='Number of estimators to use in random forest models. Hyperparameter searching requires 3 '
             'inputs: start, end, step when used with search_type geometric or grid (example: \'100,500,100\') or '
             'can be input as a list of possible values for search_type user_specified '
             '(example: \'100,200,300,400,500\')')
    parser.add_argument(
        '--rf_max_depth', dest='rf_max_depth', default=None,
        help='The maximum depth of a decision tree in the random forest.  Hyperparameter searching requires 3 '
             'inputs: start, end, step when used with search_type geometric or grid (example: \'4,7,1\') or can be '
             'input as a list of possible values for search_type user_specified (example: \'4,5,6,7\')')
    parser.add_argument(
        '--rf_max_features', dest='rf_max_features', default='32',
        help='Max number of features to split random forest nodes. Hyperparameter searching requires 3 '
             'inputs: start, end, step when used with search_type geometric or grid (example: \'16,32,4\') '
             'or can be input as a list of possible values for search_type user_specified '
             '(example: \'16,20,24,28,32\')')

    # **********************************************************************************************************
    # model_building_parameters: splitting
    parser.add_argument(
        '--base_splitter', dest='base_splitter', default='scaffold', type=str,
        help='Type of splitter to use for train/validation split if temporal split used for test set. May be random,' 
             ' scaffold, or ave_min. The allowable choices are set in splitter.py')
    parser.add_argument(
        '--butina_cutoff', dest='butina_cutoff', type=float, default=0.18,
        help='cutoff Tanimoto similarity for clustering in Butina splitter. TODO: will be implemented when DeepChem' 
             ' updates their butina splitter. ')
    parser.add_argument(
        '--cutoff_date', dest='cutoff_date', type=str, default=None,
        help='Cutoff date for test set compounds in temporal splitter. TODO: needs some formatting guidelines.')
    parser.add_argument(
        '--date_col', dest='date_col', type=str, default=None,
        help='Column in dataset containing dates for temporal splitter')
    parser.add_argument(
        '--num_folds', dest='num_folds', default=5, type=int,
        help='Number of k-folds to use in k-fold cross validation')
    parser.add_argument(
        '--previously_split', dest='previously_split', action='store_true',
        help='Boolean flag for loading in previously split train, validation, and test csv files.')
    parser.set_defaults(previously_split=False)
    parser.add_argument(
        '--split_strategy', dest='split_strategy', choices=['train_valid_test', 'k_fold_cv'],
        default='train_valid_test',
        help='Choice of splitting type between "k_fold_cv" for k fold cross validation and "train_valid_test" for a ' 
             'normal train/valid/test split. If split_test_frac or split_valid_frac are not set, "train_valid_test" '
             'sets are split according to the splitting type default.')
    parser.add_argument(
        '--split_test_frac', dest='split_test_frac', type=float, default=0.1,
        help='Fraction of data to put in held-out test set for train_valid_test split strategy.' 
             ' TODO: Behavior of split_test_frac is dependent on split_valid_frac and DeepChem')
    parser.add_argument(
        '--split_uuid', dest='split_uuid', default=None,
        help='UUID for csv file containing train, validation, and test split information. Specific to LLNL datastore')
    parser.add_argument(
        '--split_valid_frac', dest='split_valid_frac', type=float, default=0.1,
        help='Fraction of data to put in the validation set for train_valid_test split strategy.' 
             ' TODO: Behavior of split_valid_frac is dependent on split_test_frac and DeepChem')
    parser.add_argument(
        '--splitter', '-s', dest='splitter', default='scaffold', type=str,
        help='Type of splitter to use: index, random, scaffold, butina, ave_min, temporal, fingerprint, or stratified.'
             ' Used to set the splitting.py subclass. Can be input as a comma separated list for hyperparameter search'
             ' (e.g. \'scaffold\',\'random\')')

    # **********************************************************************************************************
    # model_building_parameters: transformers
    parser.add_argument(
        '--feature_transform_type', dest='feature_transform_type', choices=['normalization', 'umap'],
        default='normalization', help='type of transformation for the features')
    parser.add_argument(
        '--response_transform_type', dest='response_transform_type', default='normalization',
        help='type of normalization for the response column TODO: Not currently implemented')
    parser.add_argument(
        '--transformer_bucket', dest='transformer_bucket', default='gsk_ml',
        help='Datastore bucket where the transformer is stored. Specific to LLNL datastore system.')
    parser.add_argument(
        '--transformer_key', dest='transformer_key', type=str, default=None,
        help='Path to a saved transformer (stored as tuple, e.g. (transform_features, transform_respose)). ' 
             'Specific to LLNL datastore system.')
    parser.add_argument(
        '--transformer_oid', dest='transformer_oid', default=None,
        help='Dataset oid of the transformer saved in the datastore. Specific to LLNL datastore system. ' 
             'TODO: May be redundant with transformer_key')
    parser.add_argument(
        '--transformers', dest='transformers', action='store_false',
        help='Boolean switch for using transformation on regression output. Default is True')
    parser.set_defaults(transformers=True)

    # **********************************************************************************************************
    # model_building_parameters: UMAP
    parser.add_argument(
        '--umap_dim', dest='umap_dim', required=False, default='10',
        help='Dimension of projected feature space, if UMAP transformation is requested. Can be input as a comma '
             'separated list for hyperparameter search (e.g. \'2,6,10\').')
    parser.add_argument(
        '--umap_metric', dest='umap_metric', required=False, default='euclidean',
        help='Distance metric used, if UMAP transformation is requested. Can be input as a comma separated list '
             'for hyperparameter search (e.g. \'euclidean\',\'cityblock\')')
    parser.add_argument(
        '--umap_min_dist', dest='umap_min_dist', required=False, default='0.05',
        help='Minimum distance used in UMAP projection, if UMAP transformation is requested. Can be input as a '
             'comma separated list for hyperparameter search (e.g. \'0.01,0.02,0.05\')')
    parser.add_argument(
        '--umap_neighbors', dest='umap_neighbors', required=False, default='20',
        help='Number of nearest neighbors used in UMAP projection, if UMAP transformation is requested. Can be input '
             'as a comma separated list for hyperparameter search (e.g. \'10,20,30\')')
    parser.add_argument(
        '--umap_targ_wt', dest='umap_targ_wt', required=False, default='0.0',
        help='Weight given to training set response values in UMAP projection, if UMAP transformation is requested.'
             ' Can be input as a comma separated list for hyperparameter search (e.g. \'0.0,0.1,0.2\')')

    # **********************************************************************************************************
    # model_building_parameters: XGBoost
    parser.add_argument(
        '--xgb_colsample_bytree', dest='xgb_colsample_bytree', default='1.0',
        help='Subsample ratio of columns when constructing each tree. Can be input as a comma separated list for' 
             ' hyperparameter search (e.g. \'0.8,0.9,1.0\')')
    parser.add_argument(
        '--xgb_gamma', dest='xgb_gamma', default='0.0',
        help='Minimum loss reduction required to make a further partition on a leaf node of the tree. Can be input' 
             ' as a comma separated list for hyperparameter search (e.g. \'0.0,0.1,0.2\')')
    parser.add_argument(
        '--xgb_learning_rate', dest='xgb_learning_rate', default='0.1',
        help='Boosting learning rate (xgb\'s \"eta\"). Can be input as a comma separated list for hyperparameter' 
             ' search (e.g. \'0.1,0.01,0.001\')')
    parser.add_argument(
        '--xgb_max_depth', dest='xgb_max_depth', default='6',
        help='Maximum tree depth for base learners. Can be input as a comma separated list for hyperparameter' 
             ' search (e.g. \'4,5,6\')')
    parser.add_argument(
        '--xgb_min_child_weight', dest='xgb_min_child_weight', default='1.0',
        help='Minimum sum of instance weight(hessian) needed in a child. Can be input as a comma separated list' 
             ' for hyperparameter search (e.g. \'1.0,1.1,1.2\')')
    parser.add_argument(
        '--xgb_n_estimators', dest='xgb_n_estimators', default='100',
        help='Number of estimators to use in xgboost models. Can be input as a comma separated list for ' 
             'hyperparameter search (e.g. \'100,200,300\')')
    parser.add_argument(
        '--xgb_subsample', dest='xgb_subsample', default='1.0',
        help='Subsample ratio of the training instance. Can be input as a comma separated list for '
             'hyperparameter search (e.g. \'0.8,0.9,1.0\')')

    # **********************************************************************************************************
    # model_saving_parameters
    parser.add_argument(
        '--collection_name', dest='collection_name', required=False, default='model_tracker',
        help='MongoDB collection where models will be saved.  Specific to LLNL model tracker system.')
    parser.add_argument(
        '--data_owner', dest='data_owner', default='gsk',
        help='Option for setting group permissions for created files. Options specific to LLNL system. Options' 
             ': [\'username\', \'data_owner_group\', \'gsk\', \'public\']')
    parser.add_argument(
        '--data_owner_group', dest='data_owner_group', default='gsk_craa',
        help='When data_owner is set to data_owner_group, this is the option for custom group name of created files. ' 
             'Specific to LLNL model_tracker system.')
    parser.add_argument(
        '--model_bucket', dest='model_bucket', type=str, default='gsk_ml',
        help='Bucket in the datastore for the model. Specific to LLNL model tracker system.')
    # TODO: Model_dataset_oid is used as metadata and used in model_datasets.py
    # TODO: Model_dataset_oid is probably over-written or unused.
    parser.add_argument(
        '--model_dataset_oid', dest='model_dataset_oid', default=None,
        help='OID of the model dataset inserted into the datastore')
    parser.add_argument(
        '--model_filter', dest='model_filter', default=None,
        help='Path to the model filter configuration file. Is loaded and stored as a dictionary. ' 
             'Specific to LLNL model tracker system.')
    parser.add_argument(
        '--model_uuid', dest='model_uuid', type=str, default=None,
        help='UUID generated after model creation (pythonic_ID). Specific for LLNL model tracker system')
    output_dir_default = None
    parser.add_argument(
        '--output_dir', dest='output_dir', required=False, default=output_dir_default,
        help='File location where the model output will be saved. Defauts to <result_dir>/. ' 
             'TODO: redundant, should be removed in a later build.')
    parser.add_argument(
        '--result_dir', '-r', dest='result_dir', default='/usr/local/data', required=False,
        help='Parent of directory where result files will be written')

    # **********************************************************************************************************
    # model_metadata
    parser.add_argument(
        '--system', dest='system', default='twintron-blue',
        choices=['LC', 'twintron-blue'],
        help='System you are running on, LC or twintron-blue. Specific to LLNL system')

    # **********************************************************************************************************
    # miscellaneous_parameters
    parser.add_argument(
        '--config_file', dest='config_file', required=False, type=str, default=None,
        help='Full path to the optional configuration file. The configuration file is a set of parameters' 
             ' in .json file format. TODO: Does not send a warning if set concurrently with other parameters.')
    parser.add_argument(
        '--num_model_tasks', dest='num_model_tasks', type=int, required=False, default=1,
        help='Number of tasks to run for. 1 means a singletask model, > 1 means a multitask model')

    # **********************************************************************************************************
    # hyperparameters
    parser.add_argument(
        '--dropout_list', dest='dropout_list', required=False, default=None,
        help='Comma-separated list of dropout rates for permutation of NN layers (e.g. \'0.0,0.4,0.6\'). Used within' 
             'permutate_NNlayer_combo_params to return combinations from layer_nums, node_nums, dropout_list and ' 
             'max_final_layer_size. dropout_list is used to set the allowable permutations of dropouts. For ' 
             'hyperparameters only.')
    parser.add_argument(
        '--hyperparam', dest='hyperparam', required=False, action='store_true',
        help='Boolean flag to indicate whether we are running the hyperparameter search script')
    parser.set_defaults(hyperparam=False)
    parser.add_argument(
        '--hyperparam_uuid', dest='hyperparam_uuid', required=False, default=None,
        help='UUID of hyperparam search run model was generated in. Not applicable for single-run jobs')
    parser.add_argument(
        '--layer_nums', dest='layer_nums', required=False, default=None,
        help='Comma-separated list of number of layers for permutation of NN layers. (e.g. \'2,3,4\'). Used within'
             ' permutate_NNlayer_combo_params to return combinations from layer_nums, node_nums, dropout_list and '
             'max_final_layer_size. layer_nums is used to set the allowable lengths of layer_sizes. For '
             'hyperparameters only.')
    parser.add_argument(
        '--lc_account', dest='lc_account', required=False, default='baasic',
        help='SLURM account to charge hyperparameter batch runs to')
    parser.add_argument(
        '--max_final_layer_size', dest='max_final_layer_size', required=False, default=32,
        help='The max number of nodes in the last layer within layer_sizes and dropouts in hyperparameter search; '
             'max_final_layer_size = min(node_nums) if min(node_nums) > max_final_layer_size. (e.g. \'16,32\'). '
             'Used within permutate_NNlayer_combo_params to return combinations from layer_nums, node_nums, '
             'dropout_list and max_final_layer_size. ')
    parser.add_argument(
            '--max_jobs', dest='max_jobs', type=int, default=80,
            help='Max number of jobs to be in the queue at one time for an LC machine')
    parser.add_argument(
        '--node_nums', dest='node_nums', required=False, default=None,
        help='Comma-separated list of number of nodes per layer for permutation of NN layers. (e.g. \'4,8,16\'). '
             'Used within permutate_NNlayer_combo_params to return combinations from layer_nums, node_nums, '
             'dropout_list and max_final_layer_size. node_num is used to set the node values within layer_sizes. '
             'For hyperparameters only.')
    parser.add_argument(
            '--nn_size_scale_factor', dest='nn_size_scale_factor', type=float, default=1.0,
            help='Scaling factor for constraining network size based on number of parameters in the network for '
                 'hyperparam search')
    parser.add_argument(
        '--python_path', dest='python_path', required=False, default='python', help='Path to desired python version')
    parser.add_argument(
            '--rerun', dest= 'rerun', required=False, action='store_true',
            help='If False, check model tracker to see if a model with that particular param combination has '
                 'already been built')
    parser.set_defaults(rerun=False)
    parser.add_argument(
        '--script_dir', dest='script_dir', required=False, default='.',
        help='Path where pipeline file you want to run hyperparam search from is located')

    parser.add_argument(
        '--search_type', dest='search_type', required=False, default='grid',
        help='Type of hyperparameter search to do. Options = [grid, random, geometric, and user_specified]')

    parser.add_argument(
        '--split_only', dest='split_only', required=False, action='store_true',
        help='Boolean flag to indicate whether we want to just split the datasets when running the hyperparameter '
             'search script')
    parser.set_defaults(split_only=False)
    parser.add_argument(
        '--shortlist_key', '-sl', dest='shortlist_key', required=False, default=None,
        help='CSV file of assays of interest for hyperparameter search')
    parser.add_argument('--use_shortlist', dest='use_shortlist', action='store_true',
                        help='Boolean flag for use a list of assays in the hyperparam search')
    parser.set_defaults(use_shortlist=False)
    parser.add_argument(
        '--slurm_partition', dest='slurm_partition', required=False, default='pbatch',
        help='SLURM partition to urn hyperparameter batch runs on')




    return parser

#***********************************************************************************************************
def postprocess_args(parsed_args):
    """ Postprocessing for the parsed arguments.
    Replaces any string in null_options with a NoneType

    Replaces any string that matches replace_with_space with whitespace.

    Parses arguments in convert_to_float_list into a list of floats, if the hyperparams option is True.
    E.g. parsed_args.dropouts = "0.001,0.001 0.002,0.002 0.03,003"
        -> parsed_args.dropouts = [[0.001,0.001], [0.002,0.002], [0.03,003]]

    Parses arguments in convert_to_int_list into a list of ints, if the hyperparams options is True.
    E.g. parsed_args.layer_sizes = "10,100 20,200 30,300"
        -> parsed_args.layer_sizes = [[10,100], [20,200], [30,300]]

    Parameters in keep_as_list are kept as lists, even if there is a single item in the list.

    Parameters in convert_to_str_list are converted to a list of strings.
    E.g. parsed_args.model_type = "NN,RF"
        -> parsed_args.model_type = ['NN','RF'].

    If there is a single item in the list (no commas), the repsonse is kept as a StringType, unless it is in
    response_cols, which is passed as a list

    Setting conditional options for descriptor_key. Current only descriptor_type option is 'moe'

    Args:
        parsed_args (argparse.Namespace): Raw parsed arguments.

    Returns:
        parsed_args (argparse.Namespace): a argparse.Namespace object containing properly processed arguments.

    Raises:
        Exception: layer_sizes, dropouts, weight_init_stddevs and bias_init_consts arguments must be the same length

        Exception: parameters within not_a_list_outside_of_hyperparams are not accepted as a list if hyperparams
        is False
    """
    replace_with_space = "@"
    null_options = ['null','Null','none','None','N/A','n/a','NaN','nan','NAN','NONE','NULL','NA']

    for keys,vals in parsed_args.__dict__.items():
        if vals in null_options:
            parsed_args.__dict__[keys] = None
        if "@" in str(vals):
            parsed_args.__dict__[keys] = vals.replace(replace_with_space," ")

    #postprocessing to add in the model_filter dictionary for the model zoo.
    if parsed_args.model_filter is not None:
        #TODO: Use model_wrapper to allow for other formats?
        with open(parsed_args.model_filter) as f:
            config = json.loads(f.read())
        parsed_args.model_filter = flatten_dict(config, {})

    # Check that split_valid_frac+split_test_frac leaves room for a training set
    if parsed_args.split_strategy == 'train_valid_test':
        if parsed_args.split_valid_frac + parsed_args.split_test_frac >= 1.0:
            raise Exception("Split fractions for validation and test sets leave no room for training set.")
    elif parsed_args.split_strategy == 'k_fold_cv':
        if parsed_args.split_test_frac >= 1.0:
            raise Exception("Split fraction for test set leaves no room for training and validation data.")

    # Set conditional defaults for model_choice_score_type based on prediction_type
    if parsed_args.model_choice_score_type is None:
        if parsed_args.prediction_type == 'classification':
            parsed_args.model_choice_score_type = 'roc_auc'
        else:
            parsed_args.model_choice_score_type = 'r2'

    # Convert arguments passed as comma-separated values into lists
    if parsed_args.hyperparam:
        for item in convert_to_str_list:
            if parsed_args.__dict__[item] is not None:
                parsed_args.__dict__[item] = [x.strip() for x in parsed_args.__dict__[item].split(',')]
                if len(parsed_args.__dict__[item]) == 1 and item !='response_cols':
                    parsed_args.__dict__[item] = parsed_args.__dict__[item][0]

        for item in convert_to_numeric_list:
            if parsed_args.__dict__[item] is not None:

                # splits a list of space separated strings e.g. [--dropouts 0.001,0.001 0.002,0.002]
                # e.g. [--dropouts 0.001,0.001 0.002,0.002] -> [[0.001,0.001],[0.002,0.002]]
                current_value = parsed_args.__dict__[item].split(' ')
                newlist = []
                for vals in current_value:
                    temp_split = vals.split(',')
                    if item in convert_to_int_list:
                        newlist.append([int(x.strip()) for x in temp_split])
                    else:
                        newlist.append([float(x.strip()) for x in temp_split])
                    # Once a new list of lists is generated, pass to parsed_args
                    if len(newlist) == 1:
                        parsed_args.__dict__[item] = newlist[0]
                        #newlist is a list of lists, need to extract down to the lowest layer, as necessary
                        if len(newlist[0]) == 1 and item not in keep_as_list:
                            parsed_args.__dict__[item] = parsed_args.__dict__[item][0]
                    else:
                        parsed_args.__dict__[item] = newlist
    else:
        for item in convert_to_numeric_list:
            if parsed_args.__dict__[item] is not None:
                current_value = parsed_args.__dict__[item].split(',')
                if item in convert_to_int_list:
                    newlist = [int(x.strip()) for x in current_value]
                else:
                    newlist = [float(x.strip()) for x in current_value]
                # Once a new list of lists is generated, pass to parsed_args
                if len(newlist) == 1 and item not in keep_as_list:
                    parsed_args.__dict__[item] = newlist[0]
                else:
                    parsed_args.__dict__[item] = newlist
                if item in not_a_list_outside_of_hyperparams and isinstance(parsed_args.__dict__[item], list):
                    raise Exception("%s is not accepted as a list if hyperparams is False" %item)

        for item in not_a_str_list_outside_of_hyperparams:
            if parsed_args.__dict__[item] is not None:
                if ',' in parsed_args.__dict__[item] or ' ' in parsed_args.__dict__[item]:
                    raise Exception("%s cannot contain a comma or whitespace when hyperparams is False" %item)
        if parsed_args.__dict__['response_cols'] is not None:
            current_value = parsed_args.__dict__['response_cols'].split(',')
            parsed_args.__dict__['response_cols'] = current_value
        # Checks that the layer sizes, dropouts, weight_init_stddevs, and bias_init_consts are the same length
        # if they are non-default
        if parsed_args.layer_sizes is not None:
            nlayers = len(parsed_args.layer_sizes)
            if ((parsed_args.dropouts is not None and len(parsed_args.dropouts) != nlayers) or
                (parsed_args.weight_init_stddevs is not None and len(parsed_args.weight_init_stddevs) != nlayers) or
                (parsed_args.bias_init_consts is not None and len(parsed_args.bias_init_consts) != nlayers)):
                raise Exception("layer_sizes, dropouts, weight_init_stddevs and bias_init_consts arguments must be the "
                                "same length")
    return parsed_args

#***********************************************************************************************************
def prune_defaults(params, keep_params={}):
    """Removes parameters that are not in keep_params or in get_defaults

    Args:
        params (argparse.Namespace): Raw parsed arguments.
        keep_params (list): List of parameters to keep

    Returns:
        new_dict (dict): Pruned argument dictionary
    """
    parser = get_parser()
    new_dict = dict()
    if isinstance(params, argparse.Namespace):
        inner_dict = params.__dict__
    else:
        inner_dict = params
    for key, value in inner_dict.items():
        if key in keep_params or parser.get_default(key) not in [value, str(value)]:
            new_dict[key] = value
    return new_dict

#***********************************************************************************************************

def main(argument):
    """Entry point when script is run from a shell"""
    if argument[0] in ['--help', '-h']:
        params = parse_command_line(argument)
    else:
        params = wrapper(argument)
        print(params)
    return params

#***********************************************************************************************************

if __name__ == '__main__' and len(sys.argv) > 1:
    """Entry point when script is run from a shell. Raises an error if there are duplicate arguments"""
    just_args = [x for x in sys.argv if "--" in x]
    duplicates = set([x for x in just_args if just_args.count(x) > 1])
    if len(duplicates) > 0:
        raise ValueError(str(duplicates) + " appears several times. ")
    main(sys.argv[1:])
    sys.exit(0)
