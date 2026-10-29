#include <stdio.h>
#include <string.h>
int main(void) {
    char line[100], longest[100] = "";
    size_t max = 0;
    while (scanf("%99s", line) == 1) { /* Deliberate defect: split lines into words. */
        size_t len = strlen(line);
        if (len > max) { max = len; strcpy(longest, line); }
    }
    if (max > 0) printf("%s \n", longest);
    return 0;
}
