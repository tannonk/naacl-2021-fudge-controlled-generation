#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Example Call:

    python evaluate_simplify.py --condition_model /srv/scratch6/kew/fudge/ckpt/simplify/simplify_l4_v3/model_best.pth.tar --dataset_info /srv/scratch6/kew/fudge/ckpt/simplify/simplify_l4_v3/dataset_info --generation_model /srv/scratch6/kew/paraphrase/models/bart_large_paraNMT_filt_fr/best_model --infile /srv/scratch6/kew/ats/data/en/aligned/turk_test.tsv --batch_size 10 --condition_lambda 0 --batch_size 10

"""

from pathlib import Path
import random
import time
import pickle

from collections import namedtuple
from itertools import islice

from tqdm import tqdm
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import BartTokenizer, BartForConditionalGeneration

from data import Dataset
from model import Model
from util import save_checkpoint, ProgressMeter, AverageMeter, num_params
from constants import *
from predict_simplify_lp import predict_simplicity, generation_arg_parser

def quick_lc(infile):
    lc = 0
    with open(infile, 'rb') as inf:
        for line in inf:
            lc += 1
    return lc

def preprocess_lines(line):
    """
    Return only the source sentence from local dataset
    formats. These are expected to be tsv files with the
    source in the first column and the target(s) in the
    susbsequent columns. As input, the generator takes only
    the source.
    """
    # could add further preprocessing here...
    line = line.strip().split('\t')
    return line[0]

def infer_outfile_name_from_args(args):
    """Helper function for inferring outfile name for
    experiment tracking"""
    filename = ''
    filename += f'lambda{args.condition_lambda}'
    filename += f'_pretopk{args.precondition_topk}'
    filename += f'_beams{args.num_beams}'
    filename += f'_estop{args.do_early_stopping}'
    filename += f'_maxl{args.max_length}'
    filename += f'_minl{args.min_length}'
    filename += f'_sample{args.do_sample}'
    filename += f'_lp{args.length_penalty}'
    filename += f'_norep{args.no_repeat_ngram_size}'
    filename += f'_bgrps{args.num_beam_groups}'
    filename += f'_nbest{args.num_return_sequences}'
    filename += f'_repp{args.repetition_penalty}'
    filename += f'_soft{args.soft}'
    filename += f'_temp{args.temperature}'
    filename += f'_topk{args.top_k}'
    filename += f'_topp{args.top_p}'
    filename += '.txt'

    # expected format: outpath/generationmodel/testset/monsterhparamstring
    outfile = Path(args.outpath) / Path(args.generation_model).parts[-1] / Path(args.infile).stem / filename
    # create output dir if not exists already 
    Path(outfile).parent.mkdir(parents=True, exist_ok=True)

    if outfile.is_file():
        print(f'[!] {outfile} exists and will be overwritten...')

    return outfile
    

def main(args):

    with open(args.dataset_info, 'rb') as rf:
        dataset_info = pickle.load(rf)
    
    # load generator
    tokenizer = BartTokenizer.from_pretrained(args.generation_model)
    generator_model = BartForConditionalGeneration.from_pretrained(args.generation_model, return_dict=True).to(args.device)
    generator_model.eval()

    # load fudge conditioning model
    checkpoint = torch.load(args.condition_model, map_location=args.device)
    model_args = checkpoint['args']
    conditioning_model = Model(model_args, tokenizer.pad_token_id, tokenizer.vocab_size)
    conditioning_model.load_state_dict(checkpoint['state_dict'])
    conditioning_model = conditioning_model.to(args.device)
    conditioning_model.eval()

    if args.verbose:
        print("=> loaded checkpoint '{}' (epoch {})"
                .format(args.condition_model, checkpoint['epoch']))
        print('num params', num_params(conditioning_model))

    outfile = infer_outfile_name_from_args(args)
    
    generated_texts = 0
    start_time = time.time()
    with tqdm(total=quick_lc(args.infile)) as pbar:
        with open(outfile, 'w', encoding='utf8') as outf:
            with open(args.infile, 'r', encoding='utf8') as inf:
                while True:
                    batch_lines = list(islice(inf, args.batch_size))
                    if not batch_lines:
                        break
                    batch_lines = list(map(preprocess_lines, batch_lines))
                    batch_results = predict_simplicity(generator_model, tokenizer, conditioning_model, batch_lines, dataset_info, args)

                    assert args.num_return_sequences == 1
                    generated_texts += len(batch_results)
                    for text in batch_results:
                        outf.write(f'{text}\n')
                    
                    pbar.update(args.batch_size)

    elapsed_time = time.time() - start_time
    print(f'generated {generated_texts} texts in {elapsed_time} seconds')
    print(f'outfile: {outfile}')

if __name__=='__main__':

    parser = generation_arg_parser(description="SimpleFUDGE")
    
    # add evaluation specific arguments
    parser.add_argument('--infile', type=str, default=None, required=True, help='file containing text to run pred on')
    parser.add_argument('--outpath', type=str, default='/srv/scratch6/kew/ats/fudge/results', required=False, help='file to write generated outputs to')
    parser.add_argument('--batch_size', type=int, default=4, required=False, help='number of lines to process as a batch for prediction')
    
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    main(args)
