import numpy as np
from enum import Enum

from ctypes import c_int32
import csv


# CGRA top-level parameters
N_ROW      = 4
N_COL      = 2
N_VWR_PER_COL = 3

# Scratchpad memory configuration
SP_NWORDS = 128
SP_NLINES = 64


#### SPECIALIZED SLOTS: Sub-modules of the VWR2A top module that each perform their own purpos and have their own ISA ######


class CGRA:
    def __init__( self, kernel, memory, inputs, outputs ):
        self.cells      = [[ PE( self, c,r) for r in range(N_ROWS)] for c in range(N_COLS)]
        self.instrs     = ker_parse( kernel )
        self.memory     = memory
        self.inputs     = inputs
        self.outputs    = outputs
        self.instr2exec = 0
        self.cycles     = 0
        self.load_idx   = [0]*N_COLS
        self.store_idx  = [0]*N_COLS
        self.exit       = False

    def run( self, pr, limit ):
        steps = 0
        while not self.step(pr):
            print("-------")
            steps += 1
            if steps > limit:
                print("EXECUTION LIMIT REACHED (",limit,"steps)")
                print("Extend the execution by calling the run with argument limit=<steps>.")
                break
        return self.outputs, self.memory

    def step( self, prs="ROUT" ):
        for r in range(N_ROWS):
            for c in range(N_COLS):
                self.cells[r][c].update()
        if PRINT_OUTS: print("Instr = ", self.cycles, "(",self.instr2exec,")")
        for r in range(N_ROWS):
            for c in range(N_COLS):
                op =  self.instrs[self.instr2exec].ops[r][c]
                b ,e = self.cells[r][c].exec( op )
                if b != 0: self.instr2exec = b - 1 #To avoid more logic afterwards
                if e != 0: self.exit = True
            outs    = [ self.cells[r][i].out        for i in range(N_COLS) ]
            insts   = [ self.cells[r][i].instr      for i in range(N_COLS) ]
            ops     = [ self.cells[r][i].op         for i in range(N_COLS) ]
            reg     = [[ self.cells[r][i].regs[regs[x]]   for i in range(N_COLS) ] for x in range(len(regs)) ]
            print_out( prs, outs, insts, ops, reg )

        self.instr2exec += 1
        self.cycles += 1
        return self.exit

    def get_neighbour_address( self, r, c, dir ):
        n_r = r
        n_c = c
        if dir == "RCL": n_c = c - 1 if c > 0 else MAX_COL
        if dir == "RCR": n_c = c + 1 if c < MAX_COL else 0
        if dir == "RCT": n_r = r - 1 if r > 0 else MAX_ROW
        if dir == "RCB": n_r = r + 1 if r < MAX_ROW else 0
        return n_r, n_c

    def get_neighbour_out( self, r, c, dir ):
        n_r, n_c = self.get_neighbour_address( r, c, dir )
        return self.cells[n_r][n_c].get_out()

    def get_neighbour_flag( self, r, c, dir, flag ):
        n_r, n_c = self.get_neighbour_address( r, c, dir )
        return self.cells[n_r][n_c].get_flag( flag )

    def load_direct( self, c ):
        ret = self.inputs[  self.load_idx[c]][ c ]
        self.load_idx[c] += 1
        return int(ret)

    def store_direct( self, c, val ):
        if self.store_idx[c] >= len(self.outputs): self.outputs.append([0]*N_COLS)
        self.outputs[ self.store_idx[c] ][c] = val
        self.store_idx[c] += 1

    def load_indirect( self, add ):
        for row in self.memory[1:]:
            if int(row[0]) == add:
                return int(row[1])
        return -1

    def store_indirect( self, add, val):
        for i in range(1,len(self.memory)):
            if int(self.memory[i][0]) == add:
                self.memory[i][1] = val
                return
        self.memory.append([add, val])
        return

class PE:
    def __init__( self, parent, row, col ):
        self.parent = parent
        self.row = row
        self.col = col
        self.flags      = { "sign"   : 0,
                            "zero"   : 0,
                            "branch" : 0,
                            "exit"   : 0}
        self.instr      = ""
        self.old_out    = 0
        self.out        = 0
        self.regs       = {'R0':0, 'R1':0, 'R2':0, 'R3':0 }
        self.op         = ""
        self.instr      = ""

    def get_out( self ):
        return self.old_out

    def get_flag( self, flag ):
        return self.flags[flag]

    def fetch_val( self, val):
        if val.lstrip('-+').isnumeric():
            return int(val)
        if val == 'ROUT':
            return int( self.old_out)
        if val == 'ZERO':
            return 0
        if val in self.regs:
            return int( self.regs[val])
        return int(self.parent.get_neighbour_out( self.row, self.col, val ))

    def fetch_flag( self, dir, flag ):
        if dir == 'ROUT':
            return int( self.old_out)
        return int(self.parent.get_neighbour_flag( self.row, self.col, dir, flag ))

    def exec( self,  instr ):
        self.run_instr(instr)
        return self.flags["branch"], self.flags["exit"]

    def update( self):
        self.old_out = self.out
        self.flags["zero"]      = 1 if self.out == 0 else 0
        self.flags["sign"]      = 1 if self.out <  0 else 0
        self.flags["branch"]    = 0

    def run_instr( self, instr):
        instr   = instr.replace(',', ' ')   # Remove the commas so we can speparate arguments by spaces
        self.instr = instr                  # Save this string as instruction to show
        instr   = instr.split()             # Split into chunks
        try:
            self.op      = instr[0]
        except:
            self.op = instr

        if self.op in self.ops_arith:
            des     = instr[1]
            val1    = self.fetch_val( instr[2] )
            val2    = self.fetch_val( instr[3] )
            ret     = self.ops_arith[self.op]( val1, val2)
            if des in self.regs: self.regs[des] = ret
            self.out = ret

        elif self.op in self.ops_cond:
            des     = instr[1]
            val1    = self.fetch_val( instr[2] )
            val2    = self.fetch_val( instr[3] )
            src     = instr[4]
            method  = self.ops_cond[self.op]
            ret     = method(self, val1, val2, src)
            if des in self.regs: self.regs[des] = ret
            self.out = ret

        elif self.op in self.ops_branch:
            val1    = self.fetch_val( instr[1] )
            val2    = self.fetch_val( instr[2] )
            branch  = self.fetch_val( instr[3] )
            method = self.ops_branch[self.op]
            method(self, val1, val2, branch)

        elif self.op in self.ops_lwd:
            des = instr[1]
            ret = self.parent.load_direct( self.col )
            if des in self.regs: self.regs[des] = ret
            self.out = ret

        elif self.op in self.ops_swd:
            val = self.fetch_val( instr[1] )
            self.parent.store_direct( self.col, val )

        elif self.op in self.ops_lwi:
            des = instr[1]
            add = self.fetch_val( instr[2] )
            ret = self.parent.load_indirect(add)
            if des in self.regs: self.regs[des] = ret
            self.out = ret

        elif self.op in self.ops_swi:
            add = self.fetch_val( instr[1] )
            val = self.fetch_val( instr[2] )
            self.parent.store_indirect( add, val )
            pass

        elif self.op in self.ops_nop:
            pass # Intentional

        elif self.op in self.ops_jump:
            self.flags['branch'] = val1

        elif self.op in self.ops_exit:
            self.flags['exit'] = 1

    def sadd( val1, val2 ):
        return c_int32( val1 + val2 ).value

    def ssub( val1, val2 ):
        return c_int32( val1 - val2 ).value

    def smul( val1, val2 ):
        return c_int32( val1 * val2 ).value

    def fxpmul( val1, val2 ):
        print("Better luck next time")
        return 0

    def slt( val1, val2 ):
        return c_int32(val1 << val2).value

    def srt( val1, val2 ):
        interm_result = (c_int32(val1).value & MAX_32b)
        return c_int32(interm_result >> val2).value

    def sra( val1, val2 ):
        return c_int32(val1 >> val2).value

    def lor( val1, val2 ):
        return c_int32( val1 | val2).value

    def land( val1, val2 ):
        return c_int32( val1 & val2).value

    def lxor( val1, val2 ):
        return c_int32( ((val1& MAX_32b) ^ (val2& MAX_32b)) & MAX_32b).value

    def lnand( val1, val2 ):
        return c_int32( ~( val1 & val2 ) & MAX_32b ).value

    def lnor( val1, val2 ):
         return c_int32( ~( val1 | val2 ) & MAX_32b ).value

    def lxnor( val1, val2 ):
        return c_int32( ~( val1 ^ val2 ) & MAX_32b ).value

    def bsfa( self, val1, val2, src):
        flag = self.fetch_flag( src, 'sign')
        return val1 if flag == 1 else val2

    def bzfa( self,  val1, val2, src):
        flag = self.fetch_flag( src, 'zero')
        return val1 if flag == 1 else val2

    def beq( self,  val1, val2, branch ):
        self.flags['branch'] = branch if val1 == val2 else self.flags['branch']

    def bne( self,  val1, val2, branch ):
        self.flags['branch'] = branch if val1 != val2 else self.flags['branch']

    def bge( self,  val1, val2, branch ):
        self.flags['branch'] = branch if val1 >= val2 else self.flags['branch']
    
    def blt( self,  val1, val2, branch ):
        self.flags['branch'] = branch if val1 < val2 else self.flags['branch']

    ops_arith   = { 'SADD'      : sadd,
                    'SSUB'      : ssub,
                    'SMUL'      : smul,
                    'FXPMUL'    : fxpmul,
                    'SLT'       : slt,
                    'SRT'       : srt,
                    'SRA'       : sra,
                    'LOR'       : lor,
                    'LAND'      : land,
                    'LXOR'      : lxor,
                    'LNAND'     : lnand,
                    'LNOR'      : lnor,
                    'LXNOR'     : lxnor }

    ops_cond    = { 'BSFA'      : bsfa,
                    'BZFA'      : bzfa }

    ops_branch  = { 'BEQ'       : beq,
                    'BNE'       : bne,
                    'BLT'       : blt,
                    'BGE'       : bge }

    ops_lwd     = { 'LWD'       : '' }
    ops_swd     = { 'SWD'       : '' }
    ops_lwi     = { 'LWI'       : '' }
    ops_swi     = { 'SWI'       : '' }

    ops_nop     = { 'NOP'       : '' }
    ops_jump    = { 'JUMP'      : '' }
    ops_exit    = { 'EXIT'      : '' }

def run( kernel, version="", pr="ROUT", limit=100 ):
    ker = []
    inp = []
    oup = []
    mem = []

    with open( kernel + "/"+FILENAME_INSTR+version+EXT, 'r') as f:
        for row in csv.reader(f): ker.append(row)
    with open( kernel + "/"+FILENAME_INP+EXT, 'r') as f:
        for row in csv.reader(f): inp.append(row)
    with open( kernel + "/"+FILENAME_MEM+EXT, 'r') as f:
        for row in csv.reader(f): mem.append(row)

    oup, mem = CGRA( ker, mem, inp, oup ).run(pr, limit)

    with open( kernel + "/"+FILENAME_MEM_O+EXT, 'w+') as f:
        for row in mem: csv.writer(f).writerow(row)
    with open( kernel + "/"+FILENAME_OUP+EXT, 'w+') as f:
        for row in oup: csv.writer(f).writerow(row)

    print("\n\nEND")

