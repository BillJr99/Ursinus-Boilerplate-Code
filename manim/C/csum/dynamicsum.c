#include <stdio.h>
#include <stdlib.h>

int sum;

int main(void) {
	int* a = malloc(sizeof(int));
	int* b = malloc(sizeof(int));

	*a = 5;
	*b = 2;

	sum = *a + *b;

	printf("Five plus two is: %d\n", sum);

	free(a);
	free(b);

	return 0;
}
