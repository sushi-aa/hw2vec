#!/usr/bin/env python
#title           :hw2graph.py
#description     :This file includes the neccessary functions in hw2graph.
#author          :Rozhin
#date            :2021/03/05
#version         :0.2
#notes           :
#python_version  :3.6
#==============================================================================
from __future__ import absolute_import
from __future__ import print_function
from typing import Tuple
import pyverilog
from pyverilog.dataflow.dataflow_analyzer import VerilogDataflowAnalyzer as PyDataflowAnalyzer
from pyverilog.dataflow.optimizer import VerilogDataflowOptimizer as PyDataflowOptimizer
from pyverilog.dataflow.graphgen import VerilogGraphGenerator as PyGraphGenerator
from pyverilog.controlflow.controlflow_analyzer import VerilogControlflowAnalyzer as PyControlflowAnalyzer
from pyverilog.ast_code_generator.codegen import ASTCodeGenerator
from pyverilog.vparser.parser import parse
from optparse import OptionParser

import pyverilog.vparser.ast as vast
import pyverilog.utils.util as util
import pydot

from json import dumps
from collections import defaultdict

import os, sys
sys.path.append(os.path.dirname(sys.path[0]))

import torch
import torch.nn.functional as F

import json
import networkx as nx

from sklearn.model_selection import train_test_split
from glob import glob

from hw2vec.graph2vec.trainers import *



class JsonGraphParser:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root_path = self.cfg.raw_dataset_path.resolve()

        ''' self.graphs is a dict that stores all the hardware graphs that can be parsed from the raw datatset folder. 
            'all': means it is a collection of all graph datasets.
            'train' and 'test': store the collection of graph instances according to a prespliting result.
        '''
        self.graphs = {}

        self.node_labels = set()
        
        ''' for GNN4IP '''
        ''' self.graph_pairs/_train/_test stores the graph-pairing info. e.g. (0, 1, -1) means graph 0 and graph 1 is dissimilar. '''
        self.graph_pairs       = []
        self.graph_pairs_train = [] 
        self.graph_pairs_test  = []
        
        # self.trunk stores the hardware category information about each hardware design. e.g. in [0, 1, 1, 2, 3], hw #1 belongs to category 1.
        self.trunk = []

        # list to store names of graphs in each set
        self.training_graph_count = 0
        self.testing_graph_count = 0

        self.do_normalize = True

    def append_training_graph_data(self, data):
        if 'train' not in self.graphs: 
            self.graphs['train'] = []
        self.graphs['train'].append(data)

    def append_testing_graph_data(self, data):
        if 'test' not in self.graphs: 
            self.graphs['test'] = []
        self.graphs['test'].append(data)
    
    def append_graph_data(self, data):
        if 'all' not in self.graphs: 
            self.graphs['all'] = []
        self.graphs['all'].append(data)

    def append_graph_pair(self, pair):
        self.graph_pairs.append(pair)

    def get_graphs(self):
        if 'train' in self.graphs and 'test' in self.graphs:
            return self.graphs['train'], self.graphs['test']
        elif 'all' in self.graphs:
            return self.split_dataset(ratio=self.cfg.ratio, seed=self.cfg.seed, dataset=self.graphs['all'])

    def get_pairs(self):
        graph_pairs = self.graph_pairs if self.cfg.debug else self.graph_pairs[:100]
        self.graph_pairs_train, self.graph_pairs_test = self.split_dataset(ratio=self.cfg.ratio, seed=self.cfg.seed, dataset=graph_pairs)
        return self.graph_pairs_train, self.graph_pairs_test

    def do_pickle_dataset(self):
        with open(self.cfg.pkl_path, 'wb') as f:
            if self.cfg.debug and len(self.graph_pairs) is 0:
                if 'train' in self.graphs and 'test' in self.graphs:
                    self.graphs['train'] = self.graphs['train'][:100]
                    self.graphs['test'] = self.graphs['test'][:100] 
                elif 'all' in self.graphs:
                    self.graphs['all'] = self.graphs['all'][:200]   
            pkl.dump(self, f)

    def normalize(self):
        pass


    def read_node_labels(self, key):
        # read thru all the node labels in a dataset. 
        for json_path in glob("%s/**/**/topModule.json" % str(self.root_path/key), recursive=True):
            with open(str(json_path), 'r') as json_file:
                edge_list_dict = json.loads(json_file.read())
                for src in edge_list_dict:
                    node_name = src
                    if '_graphrename' in src:
                        node_name = src[:src.index('_graphrename')]
                    if '.' in node_name: 
                        type_of_node = node_name.split('.')[-1]
                    elif '_' in node_name:
                        type_of_node = node_name.split('_')[-1]
                    else:
                        type_of_node = node_name.lower()
                    self.node_labels.add(type_of_node)

        self.label2idx = {v:k for k, v in enumerate(list(self.node_labels))}
        self.idx2label = {v:k for k, v in self.label2idx.items()}

    def split_dataset(self, ratio, seed, dataset):
        train_size = int(len(dataset) * ratio)

        sim_diff_label = []

        for data in dataset:
            if type(data) == tuple:
                if data[2] == 1:
                    sim_diff_label.append(1)
                else:
                    sim_diff_label.append(-1)
            else:
                if data.label == 1:
                    sim_diff_label.append(1)
                else:
                    sim_diff_label.append(-1)

        return train_test_split(dataset, train_size = train_size, shuffle = True, stratify=sim_diff_label, random_state=seed)

    def get_graph(self, json_string):
        # create nx graph.
        edge_list_dict = json_string['edge_index']
        hardware_graph = nx.DiGraph()
        for src in edge_list_dict:
            node_name = src
            if '_graphrename' in src:
                node_name = src[:src.index('_graphrename')]
            if '.' in node_name: 
                type_of_node = node_name.split('.')[-1]
            elif '_' in node_name:
                type_of_node = node_name.split('_')[-1]
            else:
                type_of_node = node_name.lower()
            hardware_graph.add_node(src, x=self.label2idx[type_of_node], label=type_of_node) 
            assert(type(edge_list_dict[src]) == list)
            for neighbor in edge_list_dict[src]:
                edge_label = neighbor[0]
                dst = neighbor[1]
                hardware_graph.add_edge(src, dst)
        #TODO: perform normalization

    def get_graph_from_json(self, json_path):
        json_file = open(str(json_path), 'r')
        hardware_graph = nx.DiGraph()
        edge_list_dict = json.loads(json_file.read())
        for src in edge_list_dict:
            node_name = src
            if '_graphrename' in src:
                node_name = src[:src.index('_graphrename')]
            if '.' in node_name: 
                type_of_node = node_name.split('.')[-1]
            elif '_' in node_name:
                type_of_node = node_name.split('_')[-1]
            else:
                type_of_node = node_name.lower()
            hardware_graph.add_node(src, x=self.label2idx[type_of_node], label=type_of_node) 
            assert(type(edge_list_dict[src]) == list)
            for neighbor in edge_list_dict[src]:
                edge_label = neighbor[0]
                dst = neighbor[1]
                hardware_graph.add_edge(src, dst)

        return hardware_graph

class VerilogParser:
    '''
        the only class that interfaces with pyverilog.
        https://github.com/Microsoft/vscode-tips-and-tricks#intellisense
    ''' 

    #holds a GRAPH_GENERATOR INSTANCE
    def __init__(self, verilog_file, output_directory, top_module, generate_cfg=False, generate_ast=False):
        print("Verilog file: ", verilog_file)
        print("Output directory: ", output_directory)
        if not os.path.exists(verilog_file):
            raise IOError("File Not Found:  ")
        self.output_directory = output_directory

        #Options
        self.dfg_graph_generator = None
        self.cfg_graph_generator = None
        self.ast = None
        self.ARRAY_GEN = None
        self.CONST_DICTIONARY_GEN = None
        self.DICTIONARY_GEN = None 

        self._create_graphgen_obj(verilog_file, top_module, generate_cfg, generate_ast)

    #helper fcn to __init__, create a graph object used to generate json
    def _create_graphgen_obj(self, verilog_file, top_module, generate_cfg, generate_ast):
        dataflow_analyzer = PyDataflowAnalyzer(verilog_file, top_module)
        dataflow_analyzer.generate()
        binddict = dataflow_analyzer.getBinddict()
        terms = dataflow_analyzer.getTerms()
        
        dataflow_optimizer = PyDataflowOptimizer(terms, binddict)
        dataflow_optimizer.resolveConstant()
        resolved_terms = dataflow_optimizer.getResolvedTerms()
        resolved_binddict = dataflow_optimizer.getResolvedBinddict()
        constlist = dataflow_optimizer.getConstlist()

        if generate_cfg: 
            fsm_vars = tuple(['fsm', 'state', 'count', 'cnt', 'step', 'mode'])
            self.cfg_graph_generator = PyControlflowAnalyzer("top", terms, binddict,
                                        resolved_terms, resolved_binddict, constlist, fsm_vars)
        elif generate_ast:
            #when generating AST, determines which substructure (dictionary/array) to generate
            #before converting the json-like structure into actual json
            self.DICTIONARY_GEN = ["Source","Description","Ioport","Decl","Lvalue"]
            self.ARRAY_GEN = ["ModuleDef","Paramlist","Portlist","Input","Width","Reg","Wire","Rvalue","ParseSelect",
            "Uplus","Uminus","Ulnot","Unot","Uand","Unand","Uor","Unor","Uxnor","Power","Times","Divide","Mod","Plus",
            "Minus","Sll","Srl","Sla","Sra","LessThan","GreaterThan","LessEq","GreaterEq","Eq","Eql","NotEq","Eql","NotEql",
            "And","Xor","Xnor","Or","Land","Lor","Cond","Assign","Always","AlwaysFF","AlwaysComb","AlwaysLatch",
            "SensList","Sens","Substitution","BlockingSubstitution","NonblockingSubstitution","IfStatement","Block",
            "Initial","Plus","Output","Partselect"]
            self.CONST_DICTIONARY_GEN = ["IntConst","FloatConst","StringConst","Identifier"]

            self.ast, _ = parse([verilog_file])

        else: #generate dfg
            self.dfg_graph_generator = PyGraphGenerator(top_module, terms, binddict, resolved_terms, 
                                resolved_binddict, constlist, 
                                f'{self.output_directory}seperate_modules.pdf')
    
    #generates nested dictionary for conversion to json (AST helper)
    def _generate_ast_dict(self, ast_node):
        class_name = ast_node.__class__.__name__
        structure = {}
        #based on the token class_name, determine the value type of class_name
        if class_name in self.ARRAY_GEN:
            structure[class_name] = [getattr(ast_node, n) for n in ast_node.attr_names] if ast_node.attr_names else []
            for c in ast_node.children():
                structure[class_name].append(self._generate_ast_dict(c))
        elif class_name in self.DICTIONARY_GEN:
            structure[class_name] = self._generate_ast_dict(ast_node.children()[0])
        elif class_name in self.CONST_DICTIONARY_GEN:
            structure = {}
            structure[class_name] = getattr(ast_node,ast_node.attr_names[0])
            return structure
        else:
            raise Exception(f"Error. Token name {class_name} is invalid or has not yet been supported")
        return structure

    #generates abstract syntax tree for conversion (AST helper)
    def export_ast(self, nested_dictionary):
        print(f'Saving abstract syntax tree as json')
        #print(f'{self.output_directory}/ast.json')
        with open(f'{self.output_directory}/ast.json', 'w') as f:
            f.write(dumps(nested_dictionary, indent=2))
        print('List of root nodes saved in ast.json.\n')
        f.close()

    #generates dot file (CFG helper)
    def generate_dot_file(self, graph_format='png',no_label=False):
        assert self.cfg_graph_generator != None, "Error: Generate dot file only if you are generating CFG's "

        fsms = self.cfg_graph_generator.getFiniteStateMachines()

        print("VIEWING FSM's")
        print("LENGTH OF FSM: ", len(fsms))
        for signame, fsm in fsms.items():
            print('# SIGNAL NAME: %s' % signame)
            print('# DELAY CNT: %d' % fsm.delaycnt)
            fsm.view()
            fsm.tograph(filename=util.toFlatname(signame) + '.' + graph_format, nolabel=no_label)
        
    #generate CFG from dot file
    def export_cfg_graph(self, output='graph'):
        def default_val():
            return []
        graph = pydot.graph_from_dot_file("./file.dot")[0]

        nodes = [node.get_name() for node in graph.get_node_list()]
        root_nodes = [node.get_name() for node in graph.get_node_list() if node.obj_dict['parent_graph'] == None]
        edges = [[edge.get_source(),edge.get_destination(),edge.obj_dict['attributes']['label']] for edge in graph.get_edge_list()]
        topModule = defaultdict(default_val) #key: node, val: list of out going edges

        for edge in edges:
            if edge[2] == 'None':
                topModule[edge[0]].append("")
            else:
                topModule[edge[0]].append(edge[2])
        
        if (output=='roots'):
            print(f'Saving all {len(root_nodes)} nodes as json')
            with open(f'{self.output_directory}root_nodes.json', 'w') as f:
                f.write(dumps(root_nodes, indent=4))
            print('List of root nodes saved in root_nodes.json.\n')
            f.close()
        
        elif (output=='nodes'):
            print(f'Saving all {len(nodes)} nodes as json')
            with open(f'{self.output_directory}all_nodes.json', 'w') as f:
                f.write(dumps(nodes, indent=4))
            print('List of nodes saved in all_nodes.json.\n')
            f.close()
            
        elif (output=='edges'):
            print(f'Saving all {len(edges)} edges as json')
            with open(f'{self.output_directory}all_edges.json', 'w') as f:
                f.write(dumps(edges, indent=4))
            print('List of edges saved in all_edges.json.\n')
            f.close()
            
        elif (output=='graph'):
            print(f'Saving cfg graph dictionary as a json')
            with open(f'{self.output_directory}topModule.json', 'w') as f:
                f.write(dumps(topModule, indent=4))
            print('Saving cfg graph dictionary as a json.\n')
            f.close()
            print('The graph is saved as topModule.json.\n')
    
    # This function returns True, if the child is a child of checkParent
    def _isChild(self, graph, checkParent, child):
        # This function recursively returns a list of all the parents of a node up to the root
        def getAllParents(node):
            # if node has no parents
            if graph.in_degree(node) == 0:
                return []
            # if node has no grandparents
            elif sum([graph.in_degree(parent) for parent in graph.predecessors(node)]) == 0:
                return graph.predecessors(node)
            # recursive call, node has unknown generations of parents
            else:
                retlist = list()
                for parent in graph.predecessors(node):
                    x = getAllParents(parent)
                    x.append(parent)
                    retlist += x
                return retlist
        allParents = getAllParents(child)
        return checkParent in allParents

    #generate separate graph separate modules 
    def graph_separate_modules(self, draw_graph=False):
        # binddict with string keys
        signals = [str(bind) for bind in self.dfg_graph_generator.binddict]

        print(f'{len(signals)} signals to generate seprate subgraphs...')
        for num, signal in enumerate(sorted(signals, key=str.casefold), start=1):
            self.dfg_graph_generator.generate(signal, walk=False)
            print(f'\rProgress : {num} / {len(signals)}', end='', flush=True)
        print('\nThe subgraphs are generated.\n')

        if draw_graph:
            print(f'Saving subgraphs with {len(self.dfg_graph_generator.graph.nodes())} nodes as a pdf...')
            self.dfg_graph_generator.draw()
            print('The subgraphs are saved.\n')

    #merge the graphs
    def merge_graphs(self, draw_graph=False):
        label_to_node = dict()
        for node in self.dfg_graph_generator.graph.nodes():
            if self.dfg_graph_generator.graph.in_degree(node) == 0:
                label = node.attr['label'] if node.attr['label'] != '\\N' else str(node)
                label_to_node[label] = node
        
        deleted = 0
        print('Merging subgraphs... ')
        for num, node in enumerate(self.dfg_graph_generator.graph.nodes(), start=1):
            label = node.attr['label'] if node.attr['label'] != '\\N' else str(node)
            if '_' in label and label.replace('_', '.') in label_to_node:
                parents = self.dfg_graph_generator.graph.predecessors(node)
                self.dfg_graph_generator.graph.delete_node(node)
                deleted += 1
                for parent in parents:
                    if not self._isChild(self.dfg_graph_generator.graph, label_to_node[label.replace('_', '.')], parent):
                        self.dfg_graph_generator.graph.add_edge(parent, label_to_node[label.replace('_', '.')])
            print(f'\rProgress : {num - deleted} / {len(self.dfg_graph_generator.graph.nodes())}', end='', flush=True)
        print('\nThe signals subgraphs are merged.\n')

        if draw_graph:
            print(f'Saving merged graph with {len(self.dfg_graph_generator.graph.nodes())} nodes as a pdf...')
            self.dfg_graph_generator.draw(f'{self.output_directory}merged_graph.pdf')
            print('The graphs are saved.\n')

    def get_root_nodes(self):
        if self.dfg_graph_generator:
            return [node for node in self.dfg_graph_generator.graph.nodes() if self.dfg_graph_generator.graph.in_degree(node) == 0]

    def get_nodes(self):
        if self.dfg_graph_generator:
            return self.dfg_graph_generator.graph.nodes()
    
    def get_edges(self):
        if self.dfg_graph_generator:
            all_edges = list()
            for edge in self.dfg_graph_generator.graph.edges():
                all_edges.append((edge[0], edge[1], edge.attr['label']))
            return all_edges
    
    def get_edge_list(self):
        if self.dfg_graph_generator:
            jsondict = {}
            for node in self.dfg_graph_generator.graph.nodes():
                jsondict[str(node)] = list()
                for child in self.dfg_graph_generator.graph.successors(node):
                    edgeLabel = self.dfg_graph_generator.graph.get_edge(node, child).attr['label']
                    jsondict[str(node)].append((edgeLabel, str(child)))
            return jsondict
                    
    #export the dfg graphs
    def export_dfg_graph(self, output='graph'):
        if (output=='roots'):
            root_nodes = [node for node in self.dfg_graph_generator.graph.nodes() if self.dfg_graph_generator.graph.in_degree(node) == 0]
            print(f'Saving {len(root_nodes)} root nodes as a json...')
            with open(f'{self.output_directory}root_nodes.json', 'w') as f:
                f.write(dumps(root_nodes, indent=4))
            print('List of root nodes saved in root_nodes.json.\n')
            f.close()
            
        elif (output=='nodes'):
            all_nodes = (self.dfg_graph_generator.graph.nodes())
            print(f'Saving all {len(all_nodes)} nodes as a json...')
            with open(f'{self.output_directory}all_nodes.json', 'w') as f:
                f.write(dumps(all_nodes, indent=4))
            print('List of nodes saved in all_nodes.json.\n')
            f.close()
            
        elif (output=='edges'):
            all_edges = list()
            for edge in self.dfg_graph_generator.graph.edges():
                all_edges.append((edge[0], edge[1], edge.attr['label']))
            print(f'Saving all {len(all_edges)} edges as a json...')
            with open(f'{self.output_directory}all_edges.json', 'w') as f:
                f.write(dumps(all_edges, indent=4))
            print('List of edges is saved in all_edges.json.\n')
            f.close()
            
        elif (output=='graph'):
            jsondict = {}
            for node in self.dfg_graph_generator.graph.nodes():
                jsondict[str(node)] = list()
                for child in self.dfg_graph_generator.graph.successors(node):
                    edgeLabel = self.dfg_graph_generator.graph.get_edge(node, child).attr['label']
                    jsondict[str(node)].append((edgeLabel, str(child)))
            print(f'Saving graph dictionary as a json...')
            f = open(f'{self.output_directory}topModule.json', 'w')
            jsonstr = dumps(jsondict, indent=4)
            f.write(jsonstr)
            f.close()
            print('The graph is saved as topModule.json.\n')

    #to be refactored
    def graph_input_dependencies(self,draw_graph=False):
        labeltoNames = dict()
        for node in self.dfg_graph_generator.graph.nodes():
            label = node.attr['label'] if node.attr['label'] != '\\N' else str(node)
            if label not in labeltoNames: 
                labeltoNames[label] = list()
            labeltoNames[label].append(str(node))

        inputs = [self.dfg_graph_generator.graph.get_node(*labeltoNames[str(term).replace('.', '_')]) for x, term in zip(self.dfg_graph_generator.terms, self.dfg_graph_generator.terms.values()) if len(x.get_module_list()) == 1 and 'Input' in term.termtype]

        print('Locating nodes not connected to inputs...')
        to_delete = list()
        for num, node in enumerate(self.dfg_graph_generator.graph.nodes(), start=1):
            label = node.attr['label'] if node.attr['label'] != '\\N' else str(node)
            if label not in inputs:
                x = True
                for input_ in inputs:
                    if self._isChild(self.dfg_graph_generator.graph, node, input_):
                        x = False
                if x == True:
                    to_delete.append(node)
            print(f'\rProgress : {num} / {len(self.dfg_graph_generator.graph.nodes())}', end='', flush=True)
        print('\nRemoving nodes not connected to inputs...')
        for num, node in enumerate(to_delete, start=1):
            self.dfg_graph_generator.graph.delete_node(node)
            print(f'\rProgress : {num} / {len(to_delete)}', end='', flush=True)
        print('\nRemoval is complete.\n')
        
        if draw_graph:   
            print(f'Saving graph with {len(self.dfg_graph_generator.graph.nodes())} nodes as a pdf...')
            self.dfg_graph_generator.draw(f'{self.output_directory}input_dependencies.pdf')
            print('Graph saved.\n')

        #cleanup dot file and other residual files generated earlier
    
    def cleanup_files(self):
        for file in ['file.dot','parser.out','parsetab.py','top_state.png']:
            try:
                os.remove(file)
            except FileNotFoundError:
                pass

class DFGgenerator:
    '''
        This generator generates DFG from RTL (Register Transfer Level) Verilog code.
    '''
    def __init__(self, verilog_file, output_path, code_language='verilog', top_module='top', draw_graph=False):
        if code_language == "verilog":
            if not os.path.exists(verilog_file):
                raise IOError("file not found: " + verilog_file)
    
            print("Reading ", verilog_file)
            print(f'Outputting to : {output_path}\n')
            if not os.path.exists(f'{output_path}'):
                    os.makedirs(os.path.dirname(f'{output_path}'))
            self.verilog_parser = VerilogParser(verilog_file, output_path, top_module, generate_cfg=False)
            self._generate_DFG()
            
    def process(self):
        self.verilog_parser.graph_separate_modules()
        self.verilog_parser.merge_graphs()

    def get_graph_json(self):
        graph_json = {}
        graph_json['root_nodes'] = self.verilog_parser.get_root_nodes()
        graph_json['nodes'] = self.verilog_parser.get_nodes()
        graph_json['edges'] = self.verilog_parser.get_edges()
        graph_json['edge_index'] = self.verilog_parser.get_edge_list()
        return graph_json
    
    def _generate_DFG(self):
        self.verilog_parser.graph_separate_modules()
        self.verilog_parser.merge_graphs()
        self.verilog_parser.export_dfg_graph(output='graph')
    
    def export_nodes(self):
        self.verilog_parser.export_dfg_graph(output='nodes')
    
    def export_edges(self):
        self.verilog_parser.export_dfg_graph(output='edges')
    
    def export_root_nodes(self):
        self.verilog_parser.export_dfg_graph(output='roots')
        
    def check_dependecny(self):
        self.verilog_parser.graph_input_dependencies()
        
class CFGgenerator:
    '''
        This generator generates the Control Flow Graph (CFG) from RTL verilog code.
    '''
    def __init__(self, verilog_file, output_path, code_language="verilog", top_module="top", draw_graph=False):
        if code_language == "verilog":
            if not os.path.exists(verilog_file):
                raise IOError("file not found: " + verilog_file)
    
            print("Reading ", verilog_file)
            print(f'Outputting to : {output_path}\n')
            if not os.path.exists(f'{output_path}'):
                    os.makedirs(os.path.dirname(f'{output_path}'))
                    
            self.parser = VerilogParser(verilog_file, output_path, top_module,  generate_cfg=True)
            self._generate_CFG()
            
    def _generate_CFG(self):
        self.parser.generate_dot_file()
        self.parser.export_cfg_graph(output='graph')
        self.parser.cleanup_files()

    def export_nodes(self):
        self.verilog_parser.export_cfg_graph(output='nodes')
    
    def export_edges(self):
        self.verilog_parser.export_cfg_graph(output='edges')
    
    def export_root_nodes(self):
        self.verilog_parser.export_cfg_graph(output='roots')

class ASTgenerator:
    def __init__(self,verilog_file,output):
        self.parser = VerilogParser(verilog_file,output,"top",generate_ast=True)
    def generate_ast_json(self):
        ast_dict = self.parser._generate_ast_dict(self.parser.ast)
        self.parser.export_ast(ast_dict)
        self.parser.cleanup_files()

class PreprocessVerilog:
    '''
        This class comprise the preprocessing functions for Verilog files in RTL (Register Transfer Level) and GLN (Gate-Level Netlist).
    '''
    def __init__(self, code_language="verilog"):
        if code_language == "verilog":
            pass

    def remove_comments(input_path, target_path):
        # read the file into a list of lines
        with open(input_path,'r') as file_in:
            lines = file_in.read().split("\n")
    
        file_out = open(target_path, 'w')
        modules_dic={}
        for i,line in enumerate(lines):
            idx = line.find('/')
            file_out.write(line[0:idx]+'\n')
                    
        file_in.close()
        file_out.close()
        
        
    def rename_topModule(input_path, target_path):
        # read the file into a list of lines
        with open(input_path,'r') as file_in:
            lines = file_in.read().split("\n")
    
        modules_dic={}
        # iterate over lines, and list the module names.
        for i,line in enumerate(lines):
            words = line.split()
            for j,word in enumerate(words):
                if word == 'module':
                    module_name = words[j+1]
                    if '(' in module_name:
                        idx = module_name.find('(')
                        module_name = module_name[:idx]
                        modules_dic[module_name]= 1
                    else:
                        modules_dic[module_name]= 0
                    
        # iterate over file and count the occurance of each module name.                       
        for i,line in enumerate(lines):
            words = line.split()
            for j,word in enumerate(words):
                for m in modules_dic:
                    if word == m:
                        modules_dic[m] = modules_dic[m] + 1
        print("a dictionary of module names and the number of their occurance: ", modules_dic)
        
        # find the name of top module
        for m in modules_dic:
            if modules_dic[m] == 1:
                top_module = m
                break   
        
        # rename the top module to 'top'
        file_out = open(target_path, 'w')
        for line in lines:
            file_out.write(line.replace(top_module, 'top')+'\n')
        file_in.close()
        file_out.close()

            
            
    def flatten(input_path, target_path):
        with open(target_path+"/topModule.v", "wt") as outfile:
            print(input_path, glob(fr'{input_path}/*.v'))
            for verilog_file in glob(fr'{input_path}/*.v'):
                with open(verilog_file, "rt") as infile:
                    outfile.write(infile.read())       
                    
                    
    def remove_underscores(self, input_file):
        f = open(input_file, 'r')
        s = f.read().replace('_', '')
        f.close()
        f = open(filename, 'w')
        f.write(s)
        f.close()

    def flatten(self, input_path, output_path, top_module):
        output_path = os.path.dirname(os.path.abspath(__file__))
        with open(output_path+"/topModule.v", "wt") as outfile:
            for verilog_file in glob(fr'{input_path}/*.v'):
                with open(verilog_file, "rt") as infile:
                    outfile.write(infile.read().replace(top_module, 'top'))