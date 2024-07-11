#!/bin/bash

# takes the destination as a argument
rsync -avz --exclude 'target' --exclude '.git' --exclude '.gitignore' ../ $1:~/dora
