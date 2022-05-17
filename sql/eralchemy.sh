#!/bin/bash

# $1 is db file

eralchemy -i sqlite:///$1 -o $1.eps
