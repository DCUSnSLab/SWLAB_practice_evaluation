#include <stdio.h>
#include <string.h>
int main(void) {
    char line[101], longest[100] = "";
    size_t max = 0;
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\n")] = '\0';
        size_t len = strlen(line);
        if (len >= max) { max = len; strcpy(longest, line); } /* Wrong tie winner. */
    }
    if (max > 0) printf("%s \n", longest);
    return 0;
}
