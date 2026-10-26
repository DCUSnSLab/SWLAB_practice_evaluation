#include <stdio.h>
int main(int argc,char **argv){FILE *f=argc>1?fopen(argv[1],"r"):stdin; if(!f){perror("open");return 1;} int c;while((c=fgetc(f))!=EOF)putchar(c);if(f!=stdin)fclose(f);return 0;}
