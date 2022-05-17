	.file	"stackheapfunctions.c"
	.text
	.globl	capacity
	.bss
	.align 4
capacity:
	.space 4
	.globl	size
	.data
	.align 4
size:
	.long	10
	.globl	N
	.section .rdata,"dr"
	.align 4
N:
	.long	1000
.LC0:
	.ascii "Failed to resize\0"
	.text
	.globl	resize
	.def	resize;	.scl	2;	.type	32;	.endef
	.seh_proc	resize
resize:
	pushq	%rbp
	.seh_pushreg	%rbp
	movq	%rsp, %rbp
	.seh_setframe	%rbp, 0
	subq	$32, %rsp
	.seh_stackalloc	32
	.seh_endprologue
	movq	%rcx, 16(%rbp)
	movl	%edx, 24(%rbp)
	cmpq	$0, 16(%rbp)
	jne	.L2
	movl	$0, %eax
	jmp	.L3
.L2:
	movl	24(%rbp), %eax
	movl	%eax, size(%rip)
	movl	24(%rbp), %eax
	cltq
	salq	$2, %rax
	movq	%rax, %rdx
	movq	16(%rbp), %rcx
	call	realloc
	movq	%rax, 16(%rbp)
	cmpq	$0, 16(%rbp)
	jne	.L4
	leaq	.LC0(%rip), %rcx
	call	perror
	movl	$0, %eax
	jmp	.L3
.L4:
	movq	16(%rbp), %rax
.L3:
	addq	$32, %rsp
	popq	%rbp
	ret
	.seh_endproc
	.section .rdata,"dr"
.LC1:
	.ascii "Pushing %d\12\0"
	.text
	.globl	push
	.def	push;	.scl	2;	.type	32;	.endef
	.seh_proc	push
push:
	pushq	%rbp
	.seh_pushreg	%rbp
	movq	%rsp, %rbp
	.seh_setframe	%rbp, 0
	subq	$32, %rsp
	.seh_stackalloc	32
	.seh_endprologue
	movl	%ecx, 16(%rbp)
	movq	%rdx, 24(%rbp)
	movl	16(%rbp), %edx
	leaq	.LC1(%rip), %rcx
	call	printf
	cmpq	$0, 24(%rbp)
	jne	.L6
	movl	$0, %eax
	jmp	.L7
.L6:
	movl	capacity(%rip), %edx
	movl	size(%rip), %eax
	cmpl	%eax, %edx
	jl	.L8
	movl	size(%rip), %eax
	leal	(%rax,%rax), %edx
	movq	24(%rbp), %rax
	movq	%rax, %rcx
	call	resize
	movq	%rax, 24(%rbp)
	cmpq	$0, 24(%rbp)
	jne	.L8
	movl	$0, %eax
	jmp	.L7
.L8:
	movl	capacity(%rip), %eax
	addl	$1, %eax
	movl	%eax, capacity(%rip)
	movl	capacity(%rip), %eax
	cltq
	salq	$2, %rax
	leaq	-4(%rax), %rdx
	movq	24(%rbp), %rax
	addq	%rax, %rdx
	movl	16(%rbp), %eax
	movl	%eax, (%rdx)
	movq	24(%rbp), %rax
.L7:
	addq	$32, %rsp
	popq	%rbp
	ret
	.seh_endproc
	.section .rdata,"dr"
.LC2:
	.ascii "%d \0"
	.text
	.globl	printList
	.def	printList;	.scl	2;	.type	32;	.endef
	.seh_proc	printList
printList:
	pushq	%rbp
	.seh_pushreg	%rbp
	movq	%rsp, %rbp
	.seh_setframe	%rbp, 0
	subq	$48, %rsp
	.seh_stackalloc	48
	.seh_endprologue
	movq	%rcx, 16(%rbp)
	movl	$0, -4(%rbp)
	movl	$0, -4(%rbp)
	jmp	.L10
.L11:
	movl	-4(%rbp), %eax
	cltq
	leaq	0(,%rax,4), %rdx
	movq	16(%rbp), %rax
	addq	%rdx, %rax
	movl	(%rax), %eax
	movl	%eax, %edx
	leaq	.LC2(%rip), %rcx
	call	printf
	addl	$1, -4(%rbp)
.L10:
	movl	capacity(%rip), %eax
	subl	$1, %eax
	cmpl	%eax, -4(%rbp)
	jl	.L11
	movl	$10, %ecx
	call	putchar
	nop
	addq	$48, %rsp
	popq	%rbp
	ret
	.seh_endproc
	.def	__main;	.scl	2;	.type	32;	.endef
	.section .rdata,"dr"
.LC3:
	.ascii "Failed to allocate vector\0"
.LC4:
	.ascii "NULL vector during allocation\0"
	.text
	.globl	main
	.def	main;	.scl	2;	.type	32;	.endef
	.seh_proc	main
main:
	pushq	%rbp
	.seh_pushreg	%rbp
	movq	%rsp, %rbp
	.seh_setframe	%rbp, 0
	subq	$48, %rsp
	.seh_stackalloc	48
	.seh_endprologue
	call	__main
	movl	size(%rip), %eax
	cltq
	salq	$2, %rax
	movq	%rax, %rcx
	call	malloc
	movq	%rax, -8(%rbp)
	cmpq	$0, -8(%rbp)
	jne	.L13
	leaq	.LC3(%rip), %rcx
	call	perror
	movl	$-1, %eax
	jmp	.L14
.L13:
	movl	$0, -12(%rbp)
	movl	$0, -12(%rbp)
	jmp	.L15
.L17:
	movq	-8(%rbp), %rdx
	movl	-12(%rbp), %eax
	movl	%eax, %ecx
	call	push
	movq	%rax, -8(%rbp)
	cmpq	$0, -8(%rbp)
	jne	.L16
	leaq	.LC4(%rip), %rcx
	call	puts
	movl	$-2, %eax
	jmp	.L14
.L16:
	addl	$1, -12(%rbp)
.L15:
	movl	$1000, %eax
	cmpl	%eax, -12(%rbp)
	jl	.L17
	movq	-8(%rbp), %rax
	movq	%rax, %rcx
	call	printList
	movq	-8(%rbp), %rax
	movq	%rax, %rcx
	call	free
	movl	$0, %eax
.L14:
	addq	$48, %rsp
	popq	%rbp
	ret
	.seh_endproc
	.ident	"GCC: (GNU) 10.2.0"
	.def	realloc;	.scl	2;	.type	32;	.endef
	.def	perror;	.scl	2;	.type	32;	.endef
	.def	printf;	.scl	2;	.type	32;	.endef
	.def	putchar;	.scl	2;	.type	32;	.endef
	.def	malloc;	.scl	2;	.type	32;	.endef
	.def	puts;	.scl	2;	.type	32;	.endef
	.def	free;	.scl	2;	.type	32;	.endef
