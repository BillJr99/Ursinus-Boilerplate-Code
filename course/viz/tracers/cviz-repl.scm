;; code-viz: run a Scheme file the way the REPL would, printing the value of each top-level form
;; (unless it is unspecified), so examples that end with a bare expression show their result.
;; Usage: guile --no-auto-compile -s cviz-repl.scm PROGRAM.scm
(define (cviz-run file)
  (call-with-input-file file
    (lambda (port)
      (let loop ((form (read port)))
        (unless (eof-object? form)
          (call-with-values (lambda () (eval form (interaction-environment)))
            (lambda vals
              (for-each (lambda (v) (unless (unspecified? v) (write v) (newline))) vals)))
          (loop (read port)))))))
(cviz-run (cadr (command-line)))
