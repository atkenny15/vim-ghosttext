if !has('python3')
    echom "Vim is compiled without python support - disabling vim-ghosttext"
    finish
endif

function! s:GhostNotify()
    py3 GhostNotify()
endfunction

command! GhostStart :py3 GhostStart()
command! GhostStop :py3 GhostStop()

let s:pyscript = join([expand('<sfile>:p:h'), "..", "rplugin", "python3", "vim-ghosttext.py"], '/')
execute 'py3file ' . s:pyscript
