from src.layers import *
from src.decoder import multiClassInnerProductDecoder
from torch_geometric.data import Data
import sys, time, os
import pandas as pd
from data.utils import process_data_multiclass

torch.manual_seed(1111)
np.random.seed(1111)


# ###################################
# data processing
# ###################################
lll = int(sys.argv[-1])
data = torch.load('datasets-freebase/all.pt')
train = torch.from_numpy(pd.read_csv('data/freebase/book_lo_business/train_test_split/label.dat.train_{}'.format(lll), sep='\t', header=None).to_numpy().T)
test = torch.from_numpy(pd.read_csv('data/freebase/book_lo_business/train_test_split/label.dat.test_{}'.format(lll), sep='\t', header=None).to_numpy().T)
data.train_node_idx, data.train_node_class, data.train_range = process_data_multiclass(train, data.n_a_type)
data.test_node_idx, data.test_node_class, data.test_range = process_data_multiclass(test, data.n_a_type)

# output path
out_dir = './out/book/all-{}-2l-1l/'.format(lll)
if not os.path.exists(out_dir):
    os.makedirs(out_dir)

# node feature vector initialization
data.q_feat = sparse_id(data.n_q_node)
data.p_feat = sparse_id(data.n_p_node)
data.aa_edge_weight = torch.ones(data.n_aa_edge)
data.pp_edge_weight = torch.ones(data.n_pp_edge)
data.qq_edge_weight = torch.ones(data.n_qq_edge)
data.n_node_per_type = [(i[1] - i[0]) for i in data.test_range]
data.n_node_per_type_train = [(i[1] - i[0]) for i in data.train_range]


# output dictionary
keys = ('train_out', 'test_out')
out = Data.from_dict({k: {} for k in keys})

# sent to device
device_name = 'cuda' if torch.cuda.is_available() else 'cpu'
print(device_name)
device = torch.device(device_name)
data = data.to(device)
out = out.to(device)


# ###################################
# Model
# ###################################
class Model(Module):
    def forward(self, *input):
        pass

    def __init__(self, pp, pa, qq, qa, aa, mcip):
        super(Model, self).__init__()
        self.pp = pp
        self.pa = pa
        self.qq = qq
        self.qa = qa
        self.aa = aa
        self.mcip = mcip


# hyper-parameter setting
pp_nhids_gcn = [int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])]
pa_out = [int(sys.argv[5]), int(sys.argv[6])]
aa_nhids_gcn = [sum(pa_out)*2, int(sys.argv[8])]
learning_rate = 0.01

# model init
model = Model(
    homoGraph(pp_nhids_gcn, start_graph=True, in_dim=data.n_p_node),
    interGraph(pp_nhids_gcn[-1], pa_out[0], data.n_a_node, target_feat_dim=pa_out[-1]),
    homoGraph(pp_nhids_gcn, start_graph=True, in_dim=data.n_q_node),
    interGraph(pp_nhids_gcn[-1], pa_out[0], data.n_a_node, target_feat_dim=pa_out[-1]),
    homoGraph(aa_nhids_gcn),
    multiClassInnerProductDecoder(aa_nhids_gcn[-1], data.n_a_type)
).to(device)

# optimizer
optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)


# ###################################
# Train and Test
# ###################################
# @profile
def train(epoch):
    model.train()
    optimizer.zero_grad()

    z = model.pp(data.p_feat, data.pp_edge_idx, edge_weight=data.pp_edge_weight)
    z = model.pa(z, data.pa_edge_idx)
    z1 = model.qq(data.q_feat, data.qq_edge_idx, edge_weight=data.qq_edge_weight)
    z1 = model.qa(z1, data.qa_edge_idx)
    z = model.aa(torch.cat((z, z1), dim=1), data.aa_edge_idx, edge_weight=data.aa_edge_weight)

    score = model.mcip(z, data.train_node_idx)
    pred = torch.argmax(score, dim=1)

    loss = -torch.log(score[range(score.shape[0]), data.train_node_class] + EPS).mean()
    loss.backward()
    optimizer.step()

    micro, macro = micro_macro(data.train_node_class, pred)

    out.train_out[epoch] = np.array([micro, macro])

    print('{:3d}   loss:{:0.4f}   micro:{:0.4f}   macro:{:0.4f}'
          .format(epoch, loss.tolist(), micro, macro))

    return z, loss


def test(z):
    model.eval()

    score = model.mcip(z, data.test_node_idx)
    pred = torch.argmax(score, dim=1)

    micro, macro = micro_macro(data.test_node_class, pred)

    return micro, macro


EPOCH_NUM = int(sys.argv[1])
print('model training ...')
z = 0

# train and test
for epoch in range(EPOCH_NUM):
    time_begin = time.time()

    z, loss = train(epoch)

    micro, macro = test(z)

    print('{:3d}   loss:{:0.4f}   micro:{:0.4f}   macro:{:0.4f}    time:{:0.1f}\n'
          .format(epoch, loss.tolist(), micro, macro, (time.time() - time_begin)))

    out.test_out[epoch] = np.array([micro, macro])

# model name
name = '-{}-{}-{}'.format(pp_nhids_gcn, pa_out, aa_nhids_gcn)

if device == 'cuda':
    data = data.to('cpu')
    model = model.to('cpu')
    out = out.to('cpu')

# save model and record
torch.save(model.state_dict(), out_dir + str(EPOCH_NUM) + name + '-model.pt')
torch.save(out, out_dir + str(EPOCH_NUM) + name + '-record.pt')

with open(out_dir + str(EPOCH_NUM) + name + '.txt', 'w') as f:
    f.write(str(out.test_out[EPOCH_NUM-1]))

print('The trained model and the result record have been saved!')

torch.save(z, out_dir + str(EPOCH_NUM) + name + '-weight.pt')

