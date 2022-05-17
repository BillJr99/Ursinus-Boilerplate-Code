#include <stdio.h>
#include <stdlib.h>

int capacity = 0;
int size = 10;
const int N = 1000;

int* resize(int* vector, int newSize) {
    if(vector == NULL) return NULL;
    
    size = newSize;
    vector = (int*) realloc(vector, newSize * sizeof(int));
    
    if(vector == NULL) {
        perror("Failed to resize");
        return NULL;
    }
    
    return vector;
}

int* push(int val, int* vector) {
    printf("Pushing %d\n", val);
    if(vector == NULL) return NULL;
    
    if(capacity >= size) {
        vector = resize(vector, 2 * size);
        if(vector == NULL) return NULL;
    }
    
    capacity = capacity + 1;
    vector[capacity-1] = val;
    
    return vector;
}

void printList(int* vector) {
    int i = 0;
    
    for(i = 0; i < capacity - 1; i++) {
        printf("%d ", vector[i]);
    }
    
    printf("\n");
}

int main(void) {
	int* vec = (int*) malloc(size * sizeof(int));
    
    if(vec == NULL) {
        perror("Failed to allocate vector");
        return -1;
    }
    
    int i = 0;

    for(i = 0; i < N; i++) {
        vec = push(i, vec);
        
        if(vec == NULL) {
            printf("NULL vector during allocation\n");
            return -2;
        }
    }
    
    printList(vec);

	free(vec);

	return 0;
}
