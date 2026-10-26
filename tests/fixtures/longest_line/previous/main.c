#include <stdio.h>
#include <string.h>
int main(void) {
    char line[101], longest[100] = "";
    size_t previous = 0;
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\n")] = '\0';
        size_t len = strlen(line);
        if (len > previous) strcpy(longest, line);
        previous = len; /* Deliberate defect: forget the maximum seen so far. */
    }
    if (longest[0]) printf("%s \n", longest);
    return 0;
}
