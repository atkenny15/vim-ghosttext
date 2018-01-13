if !has('python')
    echom "Vim is compiled without python support - disabling vim-ghosttext"
    finish
endif

function! s:GhostNotify()
    python GhostNotify()
endfunction

command! GhostStart :python GhostStart()
command! GhostStop :python GhostStop()

let s:pyscript = join([expand('<sfile>:p:h'), "..", "rplugin", "python2", "vim-ghosttext.py"], '/')
execute 'pyfile ' . s:pyscript
