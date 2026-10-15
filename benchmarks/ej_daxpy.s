	.data
N:      .dword 4096     # Number of elements in the vectors
Alpha:  .dword 2        # scalar value

	.bss
	.align 3
X:      .zero 32768     # vector X(4096)*8
Y:      .zero 32768     # Vector Y(4096)*8
Z:      .zero 32768     # Vector Z(4096)*8

	.text
	.align 2
	.global main
	.type main, @function
main:
	li      a0, 0
	li      a1, 0
	call    m5_reset_stats

	ld      a0, N
	la      a1, Alpha
	la      a2, X
	la      a3, Y
	la      a4, Z

#---------------------- CODE HERE ------------------------------------



#---------------------- END CODE -------------------------------------

	li      a0, 0
	li      a1, 0
	call    m5_dump_stats

# Padding, so what the front end fetches past the call to m5_dump_stats
# before the stats are dumped is nops, and never the call to m5_exit.
	.rept   50
	nop
	.endr

	call    m5_exit
	.size   main, .-main
