/* Slide example: longest input line, first wins ties, trailing space + newline.
 * Input contract: at most 99 bytes per line (MAXLINE 100 including NUL).
 * Repairs only obsolete gets(), missing declarations and typographic quotes.
 */
#include <stdio.h>
#include <string.h>

int main(void) {
    char line[101], longest[100] = "";
    size_t max = 0;
    while (fgets(line, sizeof line, stdin)) {
        line[strcspn(line, "\n")] = '\0';
        size_t len = strlen(line);
        if (len > 99) return 2;
        if (len > max) {
            max = len;
            strcpy(longest, line);
        }
    }
    if (max > 0) printf("%s \n", longest);
    return 0;
}
