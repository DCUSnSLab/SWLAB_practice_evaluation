#include <stdio.h>
int main(int argc,char **argv){if(argc!=3)return 1;FILE *in=fopen(argv[1],"rb"),*out=fopen(argv[2],"wb");if(!in||!out)return 1;int c;while((c=fgetc(in))!=EOF)fputc(c,out);fclose(in);return fclose(out)!=0;}
