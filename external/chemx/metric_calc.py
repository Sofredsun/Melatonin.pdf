import json
import sys
import pandas as pd
import argparse
import numpy as np
from rdkit import Chem
from datasets import load_dataset
from rdkit import RDLogger 
RDLogger.DisableLog('rdApp.*')
from datasets import load_dataset

from constants import DATASETS, DATASETS_IDS, EXTRACTED_COLUMNS, NUMERIC_COLUMNS, SMILES_COLS

def convert_comma(x: str) -> str:
    """Converts commas to periods in a string, if possible."""
    try:
        return str(x.replace(',', '.'))
    except:
        return str(x)
    
def select_open_access(df_dataset: pd.DataFrame) -> pd.DataFrame:
    """Filters and returns the rows with open access (access == 1) articles in the dataset."""
    return df_dataset.loc[df_dataset['access'] == 1]

def prepare_dataset(dataset: str, dataset_id: str, n_cols: list[str], s_cols: list[str]) -> pd.DataFrame:
    """Prepares the dataset by cleaning, converting columns, and processing open-access rows."""
    dataset_hf = load_dataset(dataset_id)
    df_dataset = dataset_hf["train"].to_pandas()
    
    for col in n_cols:
        df_dataset[col] = df_dataset[col].apply(lambda x: convert_comma(x))
    
    if dataset in ['oxazolidinone', 'benzimidazole']:
        df_dataset.target_relation = df_dataset.target_relation.apply(lambda x: '=' if x == "'='" else x)

    df_dataset = df_dataset.fillna('NOT_DETECTED')
    
    if dataset in ['oxazolidinone', 'benzimidazole', 'cocrystals', 'complexes']:
        for col in s_cols:
            df_dataset[col] = df_dataset[col].apply(lambda x: Chem.MolToSmiles(Chem.MolFromSmiles(x)) if Chem.MolFromSmiles(x) != None else x)

    return select_open_access(df_dataset)

def prepare_result(
    dataset: str,
    source: str,
    cols: list[str],
    s_cols: list[str]
    ) -> pd.DataFrame:
    """Processes the results from PDF, image, or single-agent source, and formats them into a DataFrame."""
    if source == 'pdf':
        df_output = pd.read_csv(f'result/from_pdf/{dataset}_result.csv')
    elif source == 'image':
        df_output = pd.read_csv(f'result/from_image/{dataset}_result.csv', sep='\t')
    elif source == 'single_agent':
        df_result = pd.read_csv(f'result/from_single_agent/{dataset}/pred.csv')
        if dataset in ['cytotoxicity', 'seltox', 'synergy', 'magnetic']:
            df_result['pdf'] = df_result['pdf'].apply(lambda x: x + '.pdf')
        return df_result.drop_duplicates()

    processed_rows = []
    for pdf in df_output['pdf']:
        result_json = json.loads(df_output['output'][df_output['pdf'] == pdf].item())
        for sample in result_json['samples']:
            row = {k: v for k, v in zip(cols, [sample.get(col) for col in cols])}
            if dataset in ['cytotoxicity', 'seltox', 'synergy', 'magnetic']:
                row['pdf'] = pdf + '.pdf'
            else:
                row['pdf'] = pdf
            processed_rows.append(row)
    df_result = pd.DataFrame(processed_rows)

    if dataset in ['oxazolidinone', 'benzimidazole', 'cocrystals', 'complexes']:
        for col in s_cols:
            df_result[col] = df_result[col].apply(lambda x: Chem.MolToSmiles(Chem.MolFromSmiles(x)) if Chem.MolFromSmiles(x) != None else x)
        
    if source == 'pdf':
        df_result['pdf'] = df_result['pdf'].apply(lambda x: x[:-4])
    elif source == 'image':
        df_result['pdf'] = df_result['pdf'].apply(lambda x: x.split("\\")[-1])

    return df_result.drop_duplicates()

def empty_metrics(cols: list[str]) -> pd.DataFrame:
    """Creates an empty DataFrame to store metrics (tp, fp, fn, precision, recall, f1) for specified columns."""
    metrics = dict()
    for col in cols:
        metrics[col] = {"tp": 0, "fp": 0, "fn": 0, "precision": 0, "recall": 0, "f1": 0}
    return pd.DataFrame(metrics).T

def calc_metrics(
    df_true: pd.DataFrame,
    df_pred: pd.DataFrame
    ) -> pd.DataFrame:

    """Calculates precision, recall, F1 score, and confusion matrix metrics for each column in the true and predicted DataFrames."""

    metrics = {}
    from copy import deepcopy
    for col in df_true.columns:
        true_values = list(df_true[col].astype(str).values)
        pred_values = list(df_pred[col].astype(str).values)

        tv = deepcopy(true_values)
        pv = deepcopy(pred_values)

        tp = 0

        for val in tv:
            if val in pv:
                pv.pop(pv.index(val))
                tp += 1

        fp = 0

        tv = deepcopy(true_values)
        pv = deepcopy(pred_values)

        for val in pv:
            if val in tv:
                tv.pop(tv.index(val))
            else:
                fp += 1

        fn = 0

        tv = deepcopy(true_values)
        pv = deepcopy(pred_values)

        for val in tv:
            if val in pv:
                pv.pop(pv.index(val))
            else:
                fn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics[col] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1
        }

    return pd.DataFrame(metrics).T

def get_parameters() -> argparse.Namespace:
    """Parses and returns command-line arguments for dataset selection and extraction approach identification."""
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--dataset', type=str, choices=DATASETS, required=True)
    parser.add_argument('--source', type=str, choices=['image', 'pdf', 'single_agent'], required=True)
    return parser.parse_args()

def main() -> None:
    """
    Analyzes the performance of predictions by calculating evaluation metrics (precision, recall, F1 score) for a specified dataset.

    This function:
        - Loads command-line arguments to get the dataset name and data source.
        - Prepares the dataset by cleaning and processing columns based on the dataset type.
        - Prepares the results from a specified source (PDF, image, or single agent).
        - Calculates metrics (precision, recall, F1 score) for each article by comparing the dataset values and results.
        - Aggregates the metrics and averages them across all articles in the dataset.
        - Saves the resulting metrics to a CSV file for further analysis.
    """
    args = vars(get_parameters())
    dataset = args['dataset']
    source = args['source']

    dataset_id = DATASETS_IDS[dataset]
    cols = EXTRACTED_COLUMNS[dataset]
    n_cols = NUMERIC_COLUMNS[dataset]
    s_cols = SMILES_COLS[dataset]
    
    df_dataset = prepare_dataset(dataset, dataset_id, n_cols, s_cols)
    df_result = prepare_result(dataset, source, cols, s_cols)
    df_dataset['pdf'] = df_dataset['pdf'].apply(lambda x: x.lower())
    df_result['pdf'] = df_result['pdf'].apply(lambda x: x.lower())

    df_metrics = empty_metrics(cols)
    access_articles = df_dataset['pdf'].unique()

    if dataset in ['magnetic', 'seltox']:
        access_articles = set(np.load(f'src/{dataset}_articles.npy'))

    print(f'Analyze {len(access_articles)} articles...')

    for article in access_articles:
        df_dataset_doi = df_dataset.loc[df_dataset['pdf'] == article][cols]
        df_result_doi = df_result.loc[df_result['pdf'] == article][cols]
        df_metrics_doi = calc_metrics(df_dataset_doi, df_result_doi)
        df_metrics += df_metrics_doi

    df_metrics = df_metrics / len(access_articles)
    print(df_metrics)
    
    path_to_save = f'result/metrics/metrics_{dataset}_from_{source}.csv'
    df_metrics.to_csv(path_to_save)
    
    print(f'Saved to {path_to_save}!')
        
if __name__ == "__main__":
    main()