# -*- coding: utf-8 -*-
from pathlib import Path
import os
import sys
from countmacs import MAC_Counter
from nets import SQUEEZENAS_NETWORKS
from PIL import Image
import cv2
from torch.backends import cudnn
import time 
import matplotlib.pyplot as plt
import argparse
import torch
import torch.optim as optim
from torchvision.transforms import Compose, ToTensor, Normalize
import numpy as np
from pre_process import rs_norm as normalize


normalize = Compose([ToTensor(), Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])])

def map_to_rs(gt):
    from cityscapesScripts.cityscapesscripts.helpers.labels import labels
    tmp = []
    for label in labels:
        if label.trainId != 255:
            tmp.append(label.trainId)  # Here we use the trainId

    while len(tmp) <= 255:
        tmp.append(0)

    mapping = np.array(tmp)
    return mapping[gt]   


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                        help='if this option is supplied, a full layer'
                             ' by layer GigaMAC summary of the model will be printed. If this option is not supplied,'
                             ' only the total GigaMACs will be printed.')

    parser.add_argument('-m', '--only_macs', dest='only_macs', action='store_true',
                        help='if this option is supplied, no inference is run, only MAC count is printed.')

    parser.add_argument('-c', '--use_cpu', action='store_true',
                        help='If this option supplied, the network will be evaluated using the cpu.'
                             ' Otherwise the gpu will be used to run evaluation.')

    parser.add_argument('-n','--net', type=str, default="squeezenas_lat_small", choices=sorted(SQUEEZENAS_NETWORKS.keys()))

    parser.add_argument('-d', '--data_dir', default='./railsem',
                        help='Location of the dataset.'
                        , required=False)
    
    args, unknown = parser.parse_known_args()
    print(args)


    cudnn.benchmark = True
    cudnn.fastest = True

    net_name =  args.net
    net_constructor = SQUEEZENAS_NETWORKS[net_name]
    model = net_constructor()

    images_dir = os.path.join(args.data_dir,'jpgs/rs19_val')
    masks_dir = os.path.join(args.data_dir,'uint8/rs19_val')
    jsons_dir = os.path.join(args.data_dir,'jsons/rs19_val')
    DATA_DIR = Path('./railsem/uint8/rs19_val')



    os.environ['CITYSCAPES_DATASET'] = str(DATA_DIR.absolute())
    print(os.environ['CITYSCAPES_DATASET'])

    sys.path.insert(0, 'cityscapesScripts')  # add subdir to path

    RESULTS_DIR = Path('./results')
    images_ids = sorted(os.listdir(images_dir))
    images_fps = [os.path.join(images_dir, image_id) for image_id in images_ids]
    INPUT_DATA = images_fps[8000:8500]





    optimizer = optim.SGD(model.parameters(), lr=0.001, momentum=0.9)
    weight_name = './railsem_trained_weights/'+net_name+'.pth'
    checkpoint = torch.load(weight_name)
    model.load_state_dict(checkpoint['model_state_dict'])
    optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
    epoch = checkpoint['epoch']
    loss = checkpoint['loss']

    result_dir = Path(RESULTS_DIR) / net_name
    result_dir.mkdir(parents=True, exist_ok=True)

    preds_dir = result_dir / 'predictions'
    preds_dir.mkdir(exist_ok=True)
    os.environ['CITYSCAPES_RESULTS'] = str(preds_dir)



    if not args.use_cpu:
        model = model.cuda()

    print('-' * 54)
    print(f'Evaluating {net_name}')
    print('-' * 54)

    print("Counting MACs")
    counter = MAC_Counter(model, [1, 3, 1024, 2048])
    if args.verbose:
        counter.print_layers()
    macs = counter.print_summary()

    print('-' * 54)

    if args.only_macs:
        return
    with torch.no_grad():
        model = model.half()
        model.eval()

        print("Evaluating Model on the Validation Dataset")
        time_list = []
        for idx, fname in enumerate(INPUT_DATA):  # run inference and save predictions
            print(f'\rSaving prediction {idx} out of {len(INPUT_DATA)}', end='')

            ####PIL
            data = Image.open(fname)
            data = data.resize((2048, 1024), resample=1)

            ###CV2
            '''data = cv2.imread(fname,-1)
            data = cv2.resize(data,(2048, 1024))
            data = cv2.cvtColor(data, cv2.COLOR_BGR2RGB)'''

            data = normalize(data)

            data =  data.unsqueeze(0)
            data = data.half()
            if not args.use_cpu:
                data = data.cuda()

            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            output = model(data)
            end.record()
            torch.cuda.synchronize()
            time_list.append(start.elapsed_time(end))

            pred = output['preds']
            pred = torch.argmax(pred[0], dim=0)
            pred = pred.cpu().data.numpy()
            pred = map_to_rs(pred).astype(np.uint8)
            assert pred.shape == (1024, 2048), pred.shape
            preds_pil = Image.fromarray(pred, mode='L')
            name = fname.split('/')[-1]
            preds_pil.save(preds_dir / name, format='PNG')
            
        print('\nAverage latency on output in ms {}'.format(sum(time_list[100:])/400)) # first 100 runs as warm-up
        print('\n' + '-' * 54)
        sys.argv = [sys.argv[0]]




if __name__ == "__main__":
    main()