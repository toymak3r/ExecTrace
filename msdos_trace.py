#!/usr/bin/env python
# (c) 2020 Felipe Correa da Silva Sanches <juca@members.fsf.org>
# Released under the terms of the GNU GPL version 3 or later.
#
# Instruction set described at ?
#
import sys

from exec_trace import ExecTrace, ERROR, hex8, hex16

def twos_compl(v):
  if v & (1 << 7):
    v -= (1 << 8)
  return v

class MSDOS_Trace(ExecTrace):
  def __init__(self,
               exefile,
               loglevel=ERROR,
               relocation_blocks=None,
               variables={},
               subroutines={},
               stack_whitelist=[]):
    super(MSDOS_Trace, self).__init__(exefile,
                                      loglevel,
                                      relocation_blocks,
                                      variables,
                                      subroutines)
    self.cur_segment = ""

  def imm16(self, v):
    if v in self.subroutines.keys():
      return self.subroutines[v][0]
    elif v in self.variables.keys():
      return self.variables[v][0]
    else:
      return hex16(v)


  def get_label(self, addr):
    if addr in self.subroutines.keys():
      return self.subroutines[addr][0]
    elif addr in self.variables.keys():
      return self.variables[addr][0]
    else:
      return "LABEL_%04X" % addr


  def output_disasm_headers(self):
    header = "; Generated by MSDOS_ExecTrace\n"

    for addr, (label, comment) in self.subroutines.items():
      header += "%s:\tequ %s\t; %s\n" % (label, hex16(addr), comment)

    return header

  def setup_ivt(self, addr, value):
    if addr % 4 == 0:
      print(f"Registering IVT entry: 0x{value:04X}")
      self.schedule_entry_point(0x280 + value) # FIXME! the correct value will not always be 0x280 here.

  def reg8(self, value):
    return ["al", "cl", "dl", "bl",
            "ah", "ch", "dh", "bh"][value & 7]

  def reg16(self, value):
    return ["ax", "cx", "dx", "bx",
            "sp", "bp", "si", "di"][value & 7]

  def ea_disp(self, r_m):
    if r_m == 0: return "bx + si"
    if r_m == 1: return "bx + di"
    if r_m == 2: return "bp + si"
    if r_m == 3: return "bp + di"
    if r_m == 4: return "si"
    if r_m == 5: return "di"
    if r_m == 6: return "bp"
    if r_m == 7: return "bx"

  def segment_reg(self, value):
    return ["es", "cs", "ss", "ds"][value & 3]

  def disasm_instruction(self, opcode):

    if opcode == 0x26:
      self.cur_segment = "es:"
      opcode = self.fetch()
    elif opcode == 0x2e:
      self.cur_segment = "" # CS:
      opcode = self.fetch()
    elif opcode == 0xf3:
      return "rep " + self.disasm_instruction(self.fetch())

    simple_instructions = {
      0x06: "push es",
      0x07: "pop es",
      0x0e: "push cs",
      0x16: "push ss",
      0x17: "pop ss",
      0x1e: "push ds",
      0x1f: "pop ds",
      0x50: "push ax",
      0x58: "pop ax",
      0x60: "pusha",
      0x61: "popa",
      0x90: "nop",
      0x9c: "pushf",
      0x9d: "popf",
      0xa4: "movsb",
      0xfa: "cli",
    }

    if opcode in simple_instructions:
      return simple_instructions[opcode]

    elif opcode == 0x0c:
      imm = self.fetch()
      return f"or al, 0x{imm:02X}"

    elif opcode == 0x24:
      imm = self.fetch()
      return f"and al, 0x{imm:02X}"

    elif opcode == 0x2b: #SUB 	reg  r/m
      op1 = self.fetch()
      reg = (op1 >> 3) & 3
      r_m = op1 & 7
      return f"sub {self.reg16(reg)}, {self.reg16(r_m)}"

    elif opcode == 0x3d: # cmp ax, iw
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"cmp ax, 0x{imm:04X}"

    elif opcode == 0x68: # push iw
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"push 0x{imm:04X}"

    elif opcode == 0x6a: # push ib
      imm = self.fetch()
      return f"push 0x{imm:02X}"

    elif opcode == 0x72: # jc addr
      imm = self.fetch()
      addr = self.PC + twos_compl(imm)
      self.conditional_branch(addr)
      return "jc %s" % self.get_label(addr)

    elif opcode == 0x74: # je addr
      imm = self.fetch()
      addr = self.PC + twos_compl(imm)
      self.conditional_branch(addr)
      return "je %s" % self.get_label(addr)

    elif opcode == 0x75: # jne addr
      imm = self.fetch()
      addr = self.PC + twos_compl(imm)
      self.conditional_branch(addr)
      return "jne %s" % self.get_label(addr)

    elif opcode == 0x80: #  FIXME!
      foo = self.fetch()
      if foo == 0x3e:
        addr = self.fetch()
        addr = addr | (self.fetch() << 8)
        imm = self.fetch()
        return f"cmp [{self.getVariableName(addr)}], 0x{imm:02X}"
      else:
        self.illegal_instruction(opcode << 8 | foo)
        return ""


    elif opcode == 0x81: # add reg16, iw
      foo = self.fetch()
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      if foo == 0xc3:
        return f"add bx, 0x{imm:04X}"
      elif foo == 0xc2:
        return f"add dx, 0x{imm:04X}"
      else:
        self.illegal_instruction(opcode << 8 | foo)
        return ""
	
    elif opcode == 0x83: # op r/m, ib
      op1 = self.fetch()
      imm = self.fetch()

      mod = (op1 >> 6) & 3
      op = ["add", "or", "adc", "sbb",
            "and", "sub", "xor", "cmp"][(op1 >> 3) & 7]
      if mod == 0b11:
        reg = self.reg16(op1 & 7)
        return f"{op} {reg}, 0x{imm:02X}"
      else:
        imm2 = self.fetch()
        ea = self.ea_disp(op1 & 7)
        return f"{op} [{ea} + 0x{imm:02X}], 0x{imm2:02X}"
    elif opcode & 0xFC == 0x88: # DATA TRANSFER
                                # MOV = Move
                                # Register/Memory to/from Register
                                # 100010 d w | mod reg r/m
      op1 = self.fetch()
      d = (opcode > 1) & 1
      w = opcode & 1
      mod = (op1 >> 6) & 3
      reg = (op1 >> 3) & 7
      r_m = op1 & 7
      reg_str = self.segment_reg(reg)

      if mod == 0b11: # r/m is treated as a REG field
        if w==0: # byte instruction
          r_m_str = self.reg8(r_m)
        else:
          r_m_str = self.reg16(r_m)

        if d==0: # from reg
          return f"mov {r_w_str}, {reg_str}"
        else: # d==1: to reg
          return f"mov {reg_str}, {r_w_str}"

      elif mod == 0b00: # ...FIXME!
        if op1 & 0b11000111 == 0b110:  # FIXME!
          imm = self.fetch()
          imm = imm | (self.fetch() << 8)
          if reg_str == "ax":
            self.ax = imm
          return f"mov {reg_str}, {self.cur_segment}[{self.getVariableName(imm)}]"

      # FIXME!
      self.illegal_instruction(opcode << 8 | op1)
      return ""

    elif opcode == 0x8c: # DATA TRANSFER
                         # MOV = Move
                         # Segment Register to Register/Memory
                         # 10001100 mod 0 reg r/m
      op1 = self.fetch()
      mod = (op1 >> 6) & 3
      zero = (op1 >> 5) & 1; assert zero == 0
      reg = (op1 >> 3) & 3
      r_m = op1 & 7
      if mod == 0b11: # r/m is treated as a REG field
        return f"mov {self.reg16(r_m)}, {self.segment_reg(reg)}"
      else:
        # FIXME!
        self.illegal_instruction(opcode << 8 | op1)
        return ""

    elif opcode == 0x8e: # MOV 	Seg 	r/m
      op1 = self.fetch()
      reg = (op1 >> 3) & 3
      r_m = op1 & 7
      return f"mov {self.segment_reg(reg)}, {self.reg16(r_m)}"

    elif opcode == 0x8f:
      foo = self.fetch()
      if foo == 0x06:
        imm = self.fetch()
        imm = imm | (self.fetch() << 8)
        return f"pop {self.cur_segment}[{self.getVariableName(imm)}]"
      else:
        self.illegal_instruction(opcode << 8 | foo)
        return ""

    elif opcode == 0xa0: # mov al, [iw]
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"mov al, [0x{imm:04X}]"

    elif opcode == 0xa2:
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"mov {self.cur_segment}[{self.getVariableName(imm)}], al"

    elif opcode == 0xa8:
      imm = self.fetch()
      return f"test al, 0x{imm:02X}"

    elif opcode == 0xb0: # mov al, ib
      imm = self.fetch()
      return f"mov al, 0x{imm:02X}"

    elif opcode == 0xb4: # mov ah, ib
      imm = self.fetch()
      try:
        self.ax = imm << 8 | (self.ax & 0xFF)
      except:
        self.ax = imm << 8
      return f"mov ah, 0x{imm:02X}"

    elif opcode == 0xb8: # mov ax, iw
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      self.ax = imm
      return f"mov ax, 0x{imm:04X}"

    elif opcode == 0xb9: # mov cx, iw
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"mov cx, 0x{imm:04X}"

    elif opcode == 0xba: # mov dx, iw
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"mov dx, 0x{imm:04X}"

    elif opcode == 0xbb: # mov bx, iw
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"mov bx, 0x{imm:04X}"

    elif opcode == 0xbe:
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"lea si, 0x{imm:04X}"

    elif opcode == 0xbf:
      imm = self.fetch()
      imm = imm | (self.fetch() << 8)
      return f"lea di, 0x{imm:04X}"

    elif opcode == 0xcd: # int n
      imm = self.fetch()
      if self.ax & 0xff00 == 0x4C00 and imm == 0x21:
        # Program has ended and asked to return to DOS
        self.restart_from_another_entry_point()
      return f"int 0x{imm:02X}"

    elif opcode == 0xcf: # iret
      self.return_from_subroutine()
      return "iret"

    elif opcode == 0xc6: # mov ??, ?? FIXME!
      foo = self.fetch()
      if foo == 0x06:
        addr = self.fetch()
        addr = addr | (self.fetch() << 8)

        imm = self.fetch()
        return f"mov [0x{addr:04X}], 0x{imm:02X}"
      else:
        self.illegal_instruction(opcode << 8 | foo)
        return ""

    elif opcode == 0xc7:
      foo = self.fetch()
      if foo == 0x06:
        addr = self.fetch()
        addr = addr | (self.fetch() << 8)

        value = self.fetch()
        value = value | (self.fetch() << 8)

        # this is incomplete and may fail in some contexts:
        if self.cur_segment == "es:" and value <= 0x03ff:
          self.setup_ivt(addr, value)

        return f"mov {self.cur_segment}[0x{addr:04X}], 0x{value:04X}"
      else:
        self.illegal_instruction(opcode << 8 | foo)
        return ""

    elif opcode == 0xe4:
      imm = self.fetch()
      return f"in al, 0x{imm:02X}"

    elif opcode == 0xe6:
      imm = self.fetch()
      return f"out 0x{imm:02X}, al"

    elif opcode == 0xe8:
      addr = self.fetch()
      addr = addr | (self.fetch() << 8)
      addr = (self.PC + twos_compl(addr)) & 0xFFFF
      self.subroutine(addr)
      return "call %s" % self.get_label(addr)

    elif opcode == 0xe9:
      addr = self.fetch()
      addr = addr | (self.fetch() << 8)
      addr = (self.PC + twos_compl(addr)) & 0xFFFF
      self.unconditional_jump(addr)
      return "jmp %s" % self.get_label(addr)

    elif opcode == 0xeb:
      imm = self.fetch()
      addr = self.PC + twos_compl(imm)
      self.unconditional_jump(addr)
      return "jmp %s" % self.get_label(addr)

    elif opcode == 0xf7: # neg
      foo = self.fetch()
      if foo == 0xdb:
        return f"neg bx"
      elif foo == 0xe1:
        return f"mul cx"
      else:
        self.illegal_instruction(opcode << 8 | foo)
        return ""

    elif opcode == 0xff: # push ... FIXME!
      foo = self.fetch()
      if foo == 0x36:
        imm = self.fetch()
        imm = imm | (self.fetch() << 8)
        return f"push {self.cur_segment}[0x{imm:04X}]"
      else:
        self.illegal_instruction(opcode << 8 | foo)
        return ""
    else:
      self.illegal_instruction(opcode)
      return "; DISASM ERROR! Illegal instruction (opcode = %s)" % hex8(opcode)

if __name__ == '__main__':
  if len(sys.argv) != 2:
    print("usage: {} <filename.exe>".format(sys.argv[0]))
  else:
    program = sys.argv[1]
    print("disassembling {}...".format(program))

    # MZ DOS header format described at:
    # http://www.delorie.com/djgpp/doc/exe/
    #
    # And also here:
    # https://web.archive.org/web/20100420081240/http://www.frontiernet.net:80/~fys/exehdr.htm
    exe = open(program ,"rb")
    header = exe.read(0x1B)
    image_last_page_size = header[0x03] << 8 | header[0x02]
    image_num_pages = header[0x05] << 8 | header[0x04]    
    num_relocs = header[0x07] << 8 | header[0x06]
    header_size = header[0x09] << 8 | header[0x08]    
    initial_IP = header[0x15] << 8 | header[0x14]
    initial_CS = header[0x17] << 8 | header[0x16]
    reloc_table_offset = header[0x19] << 8 | header[0x18]

    exe_relocs = []
    exe.seek(reloc_table_offset)
    reloc_table = exe.read(4*num_relocs)
    for i in range(num_relocs):
      offset = reloc_table[4*i + 1] << 8 | reloc_table[4*i]
      segment = reloc_table[4*i + 3] << 8 | reloc_table[4*i + 2]
      exe_relocs.append((offset, segment))

    exe.close()

    image_size = image_last_page_size + 512 * image_num_pages

    print(f"Initial CS:IP = {initial_CS:04X}:{initial_IP:04X}\n"
          f"Num Relocs = {num_relocs}\n"
          f"Header size = {header_size} paragraphs = {header_size*16} bytes\n"
          f"Image size = {image_size} bytes\n"
          f"program = {program}\n"
          f"Reloc. Table Offset = {reloc_table_offset:04X}\n"
          f"Relocations:")
    for reloc in exe_relocs:
      print(f"  offset:{reloc[0]:04X} segment:{reloc[1]:04X}")

    entry =  initial_CS * 16 + initial_IP
    reloc = [(header_size*16, 0, image_size)]

    trace = MSDOS_Trace(program,
                        relocation_blocks=reloc)
    trace.run(entry_points=[entry])
    trace.save_disassembly_listing("{}.asm".format(program.split(".")[0]))
